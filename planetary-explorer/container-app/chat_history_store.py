"""Owner-isolated chat history persistence contracts and sanitization."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlsplit, urlunsplit


MAX_DOCUMENT_BYTES = 1_750_000
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_EXPORT_BYTES = 100 * 1024 * 1024
MAX_ATTACHMENTS = 20
MAX_COSMOS_WRITE_ATTEMPTS = 4
MAX_MESSAGES = 200
MAX_MESSAGE_CONTENT_CHARS = 100_000
MAX_TITLE_CHARS = 96

_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_URL_PATTERN = re.compile(r"https?://[^\s<>\]\[()]+", re.IGNORECASE)
_SENSITIVE_QUERY_KEYS = {
    "accesstoken",
    "apikey",
    "code",
    "key",
    "sig",
    "signature",
    "token",
}
_BLOCKED_KEYS = {
    "accesstoken",
    "afterscreenshot",
    "apikey",
    "assets",
    "authorization",
    "beforescreenshot",
    "clientsecret",
    "credential",
    "imagerybase64",
    "password",
    "refreshtoken",
    "sastoken",
    "screenshot",
    "secret",
    "stacitems",
    "token",
}
_MESSAGE_KEYS = {
    "content",
    "dataSource",
    "role",
    "source",
    "stacRouting",
    "tilesAvailable",
    "timestamp",
    "toolTrace",
    "toolsUsed",
}
_CONTEXT_KEYS = {
    "map",
    "pin",
    "reasoningEffort",
    "selectedDataset",
    "selectedModel",
    "selectedModule",
    "stacMode",
}


class ChatHistoryError(Exception):
    """Base exception for chat-history operations."""


class ChatHistoryNotFoundError(ChatHistoryError):
    """Raised when a session or attachment is not owned by the caller."""


class ChatHistoryValidationError(ChatHistoryError):
    """Raised when a session cannot be safely persisted."""


class ChatHistoryConflictError(ChatHistoryError):
    """Raised when an older client snapshot would replace newer history."""


def utc_now_iso() -> str:
    """Return the current UTC timestamp in an interoperable ISO format."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_session_id(session_id: str) -> str:
    """Validate and return a client-visible session identifier."""
    if not _SESSION_ID_PATTERN.fullmatch(session_id):
        raise ChatHistoryValidationError(
            "Session id must be 1-128 URL-safe characters."
        )
    return session_id


def opaque_owner_key(owner_id: str) -> str:
    """Return a non-reversible owner prefix suitable for blob paths."""
    return hashlib.sha256(owner_id.encode("utf-8")).hexdigest()


def _redact_sensitive_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        query_keys = {
            re.sub(r"[^a-z0-9]", "", key.casefold())
            for key, _ in parse_qsl(parsed.query)
        }
        if query_keys & _SENSITIVE_QUERY_KEYS:
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "<redacted>", ""))
    except ValueError:
        return url
    return url


def _sanitize_string(value: str, *, limit: int = MAX_MESSAGE_CONTENT_CHARS) -> str:
    redacted = _URL_PATTERN.sub(lambda match: _redact_sensitive_url(match.group(0)), value)
    redacted = re.sub(
        r"(?i)\bBearer\s+[A-Za-z0-9._~-]+",
        "Bearer <redacted>",
        redacted,
    )
    return redacted[:limit]


def sanitize_value(value: Any, *, parent_key: str = "") -> Any:
    """Strip credentials, screenshots, and oversized catalog payloads recursively."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold())
            if normalized_key in _BLOCKED_KEYS:
                continue
            sanitized[key] = sanitize_value(child, parent_key=normalized_key)
        return sanitized
    if isinstance(value, list):
        return [sanitize_value(item, parent_key=parent_key) for item in value[:500]]
    if isinstance(value, str):
        return _sanitize_string(value)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _sanitize_string(str(value))


def _normalize_message(raw_message: Any) -> dict[str, Any] | None:
    if not isinstance(raw_message, dict):
        return None
    role = raw_message.get("role")
    content = raw_message.get("content")
    if role not in {"user", "assistant"} or not isinstance(content, str):
        return None

    message = {
        key: raw_message[key]
        for key in _MESSAGE_KEYS
        if key in raw_message
    }
    message["role"] = role
    message["content"] = _sanitize_string(content)
    message["timestamp"] = _sanitize_string(
        str(raw_message.get("timestamp") or utc_now_iso()),
        limit=64,
    )
    return sanitize_value(message)


def _derive_title(messages: list[dict[str, Any]]) -> str:
    first_user_message = next(
        (message["content"] for message in messages if message["role"] == "user"),
        "New analysis",
    )
    compact = re.sub(r"\s+", " ", first_user_message).strip()
    return compact[:MAX_TITLE_CHARS] or "New analysis"


def normalize_session_document(
    owner_id: str,
    session_id: str,
    payload: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded Cosmos document from a client session snapshot."""
    validate_session_id(session_id)
    if not isinstance(payload, dict):
        raise ChatHistoryValidationError("Session payload must be a JSON object.")
    if (existing or {}).get("deleting") is True:
        raise ChatHistoryConflictError(
            "Chat session deletion is in progress; retry after it completes."
        )

    existing_revision = int((existing or {}).get("clientRevision") or 0)
    requested_revision = payload.get("clientRevision")
    if requested_revision is None:
        client_revision = existing_revision + 1
    elif (
        isinstance(requested_revision, bool)
        or not isinstance(requested_revision, int)
        or requested_revision < 1
    ):
        raise ChatHistoryValidationError("clientRevision must be a positive integer.")
    else:
        client_revision = requested_revision
    if existing is not None and client_revision <= existing_revision:
        raise ChatHistoryConflictError(
            "A newer chat snapshot is already saved; reload the session before retrying."
        )

    messages = [
        normalized
        for raw_message in list(payload.get("messages") or [])[-MAX_MESSAGES:]
        if (normalized := _normalize_message(raw_message)) is not None
    ]
    raw_context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    context = sanitize_value({
        key: raw_context[key]
        for key in _CONTEXT_KEYS
        if key in raw_context
    })
    now = utc_now_iso()
    requested_title = payload.get("title")
    title = (
        re.sub(r"\s+", " ", _sanitize_string(requested_title, limit=MAX_TITLE_CHARS)).strip()
        if isinstance(requested_title, str)
        else _derive_title(messages)
    )
    document = {
        "id": session_id,
        "sessionId": session_id,
        "ownerId": owner_id,
        "schemaVersion": 2,
        "clientRevision": client_revision,
        "title": title or _derive_title(messages),
        "createdAt": (existing or {}).get("createdAt") or now,
        "updatedAt": now,
        "messageCount": len(messages),
        "messages": messages,
        "context": context,
        "attachments": copy.deepcopy((existing or {}).get("attachments") or []),
    }
    encoded = json.dumps(document, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_DOCUMENT_BYTES:
        raise ChatHistoryValidationError(
            "Session is too large to save. Start a new chat or remove large tool output."
        )
    return document


def public_session_document(document: dict[str, Any]) -> dict[str, Any]:
    """Remove internal owner, blob, and Cosmos metadata before returning a session."""
    public = copy.deepcopy(document)
    public.pop("ownerId", None)
    for key in list(public):
        if key.startswith("_"):
            public.pop(key, None)
    for attachment in public.get("attachments", []):
        attachment.pop("blobName", None)
    return public


def session_summary(document: dict[str, Any]) -> dict[str, Any]:
    """Return the compact list representation of a session."""
    public = public_session_document(document)
    return {
        key: public[key]
        for key in (
            "sessionId",
            "title",
            "createdAt",
            "updatedAt",
            "messageCount",
            "attachments",
        )
        if key in public
    }


class ChatHistoryRepository(Protocol):
    """Persistence contract implemented by memory and Cosmos repositories."""

    async def list_sessions(self, owner_id: str) -> list[dict[str, Any]]: ...

    async def get_session(self, owner_id: str, session_id: str) -> dict[str, Any]: ...

    async def upsert_session(
        self,
        owner_id: str,
        session_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def delete_session(
        self,
        owner_id: str,
        session_id: str,
        *,
        expected_etag: str | None = None,
    ) -> dict[str, Any]: ...

    async def mark_deleting(
        self,
        owner_id: str,
        session_id: str,
        *,
        expected_etag: str | None = None,
    ) -> dict[str, Any]: ...

    async def add_attachment(
        self,
        owner_id: str,
        session_id: str,
        attachment: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def remove_attachment(
        self,
        owner_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any]: ...


class ArtifactStore(Protocol):
    """Private file persistence used by chat-history attachments."""

    async def upload(
        self,
        owner_id: str,
        session_id: str,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> dict[str, Any]: ...

    async def download(self, attachment: dict[str, Any]) -> bytes: ...

    async def delete(self, attachment: dict[str, Any]) -> None: ...

    async def touch(self, attachment: dict[str, Any]) -> None: ...


class InMemoryChatHistoryRepository:
    """Process-local repository used by local development and unit tests."""

    def __init__(self) -> None:
        self._documents: dict[tuple[str, str], dict[str, Any]] = {}

    async def list_sessions(self, owner_id: str) -> list[dict[str, Any]]:
        owned = [
            session_summary(document)
            for (document_owner, _), document in self._documents.items()
            if document_owner == owner_id
        ]
        return sorted(owned, key=lambda item: item["updatedAt"], reverse=True)

    async def get_session(self, owner_id: str, session_id: str) -> dict[str, Any]:
        validate_session_id(session_id)
        document = self._documents.get((owner_id, session_id))
        if document is None:
            raise ChatHistoryNotFoundError("Chat session not found.")
        return copy.deepcopy(document)

    async def upsert_session(
        self,
        owner_id: str,
        session_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self._documents.get((owner_id, session_id))
        document = normalize_session_document(
            owner_id,
            session_id,
            payload,
            existing=existing,
        )
        document["_etag"] = str(int((existing or {}).get("_etag") or 0) + 1)
        self._documents[(owner_id, session_id)] = document
        return copy.deepcopy(document)

    async def delete_session(
        self,
        owner_id: str,
        session_id: str,
        *,
        expected_etag: str | None = None,
    ) -> dict[str, Any]:
        document = await self.get_session(owner_id, session_id)
        if expected_etag is not None and document.get("_etag") != expected_etag:
            raise ChatHistoryConflictError(
                "Chat session changed during deletion; retry the request."
            )
        del self._documents[(owner_id, session_id)]
        return document

    async def mark_deleting(
        self,
        owner_id: str,
        session_id: str,
        *,
        expected_etag: str | None = None,
    ) -> dict[str, Any]:
        document = await self.get_session(owner_id, session_id)
        if document.get("deleting") is True:
            return document
        if expected_etag is not None and document.get("_etag") != expected_etag:
            raise ChatHistoryConflictError(
                "Chat session changed during deletion; retry the request."
            )
        document["deleting"] = True
        document["updatedAt"] = utc_now_iso()
        document["_etag"] = str(int(document.get("_etag") or 0) + 1)
        self._documents[(owner_id, session_id)] = document
        return copy.deepcopy(document)

    async def add_attachment(
        self,
        owner_id: str,
        session_id: str,
        attachment: dict[str, Any],
    ) -> dict[str, Any]:
        document = await self.get_session(owner_id, session_id)
        if document.get("deleting") is True:
            raise ChatHistoryConflictError("Chat session deletion is in progress.")
        attachments = [
            item for item in document.get("attachments", [])
            if item.get("id") != attachment.get("id")
        ]
        if len(attachments) >= MAX_ATTACHMENTS:
            raise ChatHistoryValidationError(
                f"A session can contain at most {MAX_ATTACHMENTS} files."
            )
        document["attachments"] = attachments + [copy.deepcopy(attachment)]
        document["updatedAt"] = utc_now_iso()
        document["_etag"] = str(int(document.get("_etag") or 0) + 1)
        self._documents[(owner_id, session_id)] = document
        return copy.deepcopy(document)

    async def remove_attachment(
        self,
        owner_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any]:
        document = await self.get_session(owner_id, session_id)
        if document.get("deleting") is True:
            raise ChatHistoryConflictError("Chat session deletion is in progress.")
        attachments = document.get("attachments", [])
        removed = next(
            (item for item in attachments if item.get("id") == attachment_id),
            None,
        )
        if removed is None:
            raise ChatHistoryNotFoundError("Attachment not found.")
        document["attachments"] = [
            item for item in attachments if item.get("id") != attachment_id
        ]
        document["updatedAt"] = utc_now_iso()
        document["_etag"] = str(int(document.get("_etag") or 0) + 1)
        self._documents[(owner_id, session_id)] = document
        return copy.deepcopy(removed)


def _is_not_found_error(error: Exception) -> bool:
    return getattr(error, "status_code", None) == 404


def _is_status_error(error: Exception, status_code: int) -> bool:
    return getattr(error, "status_code", None) == status_code


class CosmosChatHistoryRepository:
    """Azure Cosmos DB for NoSQL repository using Microsoft Entra credentials."""

    def __init__(
        self,
        endpoint: str,
        database_name: str,
        container_name: str,
        *,
        container_client: Any | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._database_name = database_name
        self._container_name = container_name
        self._container = container_client
        self._client: Any | None = None
        self._credential: Any | None = None

    async def _get_container(self) -> Any:
        if self._container is not None:
            return self._container
        try:
            from azure.cosmos.aio import CosmosClient
            from azure.identity.aio import DefaultAzureCredential
        except ImportError as exc:
            raise ChatHistoryError(
                "Cosmos chat history requires azure-cosmos and azure-identity."
            ) from exc

        self._credential = DefaultAzureCredential()
        self._client = CosmosClient(self._endpoint, credential=self._credential)
        database = self._client.get_database_client(self._database_name)
        self._container = database.get_container_client(self._container_name)
        return self._container

    async def list_sessions(self, owner_id: str) -> list[dict[str, Any]]:
        container = await self._get_container()
        query = (
            "SELECT c.sessionId, c.title, c.createdAt, c.updatedAt, "
            "c.messageCount, c.attachments FROM c "
            "WHERE c.ownerId = @ownerId ORDER BY c.updatedAt DESC"
        )
        parameters = [{"name": "@ownerId", "value": owner_id}]
        results = container.query_items(
            query=query,
            parameters=parameters,
            partition_key=owner_id,
        )
        return [session_summary(document) async for document in results]

    async def get_session(self, owner_id: str, session_id: str) -> dict[str, Any]:
        validate_session_id(session_id)
        container = await self._get_container()
        try:
            return await container.read_item(item=session_id, partition_key=owner_id)
        except Exception as exc:
            if _is_not_found_error(exc):
                raise ChatHistoryNotFoundError("Chat session not found.") from exc
            raise

    async def upsert_session(
        self,
        owner_id: str,
        session_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        container = await self._get_container()
        from azure.core import MatchConditions

        for _attempt in range(MAX_COSMOS_WRITE_ATTEMPTS):
            try:
                existing = await self.get_session(owner_id, session_id)
            except ChatHistoryNotFoundError:
                document = normalize_session_document(
                    owner_id,
                    session_id,
                    payload,
                )
                try:
                    return await container.create_item(document)
                except Exception as exc:
                    if _is_status_error(exc, 409):
                        continue
                    raise

            document = normalize_session_document(
                owner_id,
                session_id,
                payload,
                existing=existing,
            )
            try:
                return await container.replace_item(
                    item=session_id,
                    body=document,
                    etag=existing.get("_etag"),
                    match_condition=MatchConditions.IfNotModified,
                )
            except Exception as exc:
                if _is_status_error(exc, 412):
                    continue
                raise
        raise ChatHistoryError("Chat session changed repeatedly; retry the save.")

    async def delete_session(
        self,
        owner_id: str,
        session_id: str,
        *,
        expected_etag: str | None = None,
    ) -> dict[str, Any]:
        document = None
        if expected_etag is None:
            document = await self.get_session(owner_id, session_id)
            expected_etag = document.get("_etag")
        container = await self._get_container()
        from azure.core import MatchConditions

        try:
            await container.delete_item(
                item=session_id,
                partition_key=owner_id,
                etag=expected_etag,
                match_condition=MatchConditions.IfNotModified,
            )
        except Exception as exc:
            if _is_status_error(exc, 412):
                raise ChatHistoryConflictError(
                    "Chat session changed during deletion; retry the request."
                ) from exc
            raise
        return document or {"id": session_id, "sessionId": session_id}

    async def mark_deleting(
        self,
        owner_id: str,
        session_id: str,
        *,
        expected_etag: str | None = None,
    ) -> dict[str, Any]:
        container = await self._get_container()
        from azure.core import MatchConditions

        document = await self.get_session(owner_id, session_id)
        if document.get("deleting") is True:
            return document
        if expected_etag is not None and document.get("_etag") != expected_etag:
            raise ChatHistoryConflictError(
                "Chat session changed during deletion; retry the request."
            )
        document["deleting"] = True
        document["updatedAt"] = utc_now_iso()
        try:
            return await container.replace_item(
                item=session_id,
                body=document,
                etag=document.get("_etag"),
                match_condition=MatchConditions.IfNotModified,
            )
        except Exception as exc:
            if _is_status_error(exc, 412):
                raise ChatHistoryConflictError(
                    "Chat session changed during deletion; retry the request."
                ) from exc
            raise

    async def add_attachment(
        self,
        owner_id: str,
        session_id: str,
        attachment: dict[str, Any],
    ) -> dict[str, Any]:
        container = await self._get_container()
        from azure.core import MatchConditions

        for _attempt in range(MAX_COSMOS_WRITE_ATTEMPTS):
            document = await self.get_session(owner_id, session_id)
            if document.get("deleting") is True:
                raise ChatHistoryConflictError("Chat session deletion is in progress.")
            attachments = [
                item for item in document.get("attachments", [])
                if item.get("id") != attachment.get("id")
            ]
            if len(attachments) >= MAX_ATTACHMENTS:
                raise ChatHistoryValidationError(
                    f"A session can contain at most {MAX_ATTACHMENTS} files."
                )
            document["attachments"] = attachments + [copy.deepcopy(attachment)]
            document["updatedAt"] = utc_now_iso()
            try:
                return await container.replace_item(
                    item=session_id,
                    body=document,
                    etag=document.get("_etag"),
                    match_condition=MatchConditions.IfNotModified,
                )
            except Exception as exc:
                if _is_status_error(exc, 412):
                    continue
                raise
        raise ChatHistoryError("Chat session changed repeatedly; retry the upload.")

    async def remove_attachment(
        self,
        owner_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any]:
        container = await self._get_container()
        from azure.core import MatchConditions

        for _attempt in range(MAX_COSMOS_WRITE_ATTEMPTS):
            document = await self.get_session(owner_id, session_id)
            if document.get("deleting") is True:
                raise ChatHistoryConflictError("Chat session deletion is in progress.")
            attachments = document.get("attachments", [])
            removed = next(
                (item for item in attachments if item.get("id") == attachment_id),
                None,
            )
            if removed is None:
                raise ChatHistoryNotFoundError("Attachment not found.")
            document["attachments"] = [
                item for item in attachments if item.get("id") != attachment_id
            ]
            document["updatedAt"] = utc_now_iso()
            try:
                await container.replace_item(
                    item=session_id,
                    body=document,
                    etag=document.get("_etag"),
                    match_condition=MatchConditions.IfNotModified,
                )
                return copy.deepcopy(removed)
            except Exception as exc:
                if _is_status_error(exc, 412):
                    continue
                raise
        raise ChatHistoryError("Chat session changed repeatedly; retry the deletion.")


def _safe_filename(filename: str) -> str:
    normalized = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "_", filename).strip(" ._")
    if not normalized:
        raise ChatHistoryValidationError("File name is required.")
    return normalized[:160]


def _build_attachment(
    owner_id: str,
    session_id: str,
    filename: str,
    content_type: str,
    content: bytes,
) -> dict[str, Any]:
    validate_session_id(session_id)
    if not content:
        raise ChatHistoryValidationError("File is empty.")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise ChatHistoryValidationError("File exceeds the 25 MB upload limit.")
    attachment_id = str(uuid.uuid4())
    safe_filename = _safe_filename(filename)
    session_key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    blob_name = f"{opaque_owner_key(owner_id)}/{session_key}/{attachment_id}/{safe_filename}"
    return {
        "id": attachment_id,
        "name": safe_filename,
        "contentType": _sanitize_string(content_type or "application/octet-stream", limit=128),
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "createdAt": utc_now_iso(),
        "blobName": blob_name,
    }


class InMemoryArtifactStore:
    """Process-local artifact storage used in tests and local development."""

    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}

    async def upload(
        self,
        owner_id: str,
        session_id: str,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> dict[str, Any]:
        attachment = _build_attachment(
            owner_id,
            session_id,
            filename,
            content_type,
            content,
        )
        self._files[attachment["blobName"]] = bytes(content)
        return attachment

    async def download(self, attachment: dict[str, Any]) -> bytes:
        content = self._files.get(str(attachment.get("blobName") or ""))
        if content is None:
            raise ChatHistoryNotFoundError("Attachment content not found.")
        return bytes(content)

    async def delete(self, attachment: dict[str, Any]) -> None:
        self._files.pop(str(attachment.get("blobName") or ""), None)

    async def touch(self, attachment: dict[str, Any]) -> None:
        if str(attachment.get("blobName") or "") not in self._files:
            raise ChatHistoryNotFoundError("Attachment content not found.")


class BlobArtifactStore:
    """Private Azure Blob artifact storage using Microsoft Entra credentials."""

    def __init__(
        self,
        endpoint: str,
        container_name: str,
        *,
        container_client: Any | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._container_name = container_name
        self._container = container_client
        self._service: Any | None = None
        self._credential: Any | None = None

    async def _get_container(self) -> Any:
        if self._container is not None:
            return self._container
        try:
            from azure.identity.aio import DefaultAzureCredential
            from azure.storage.blob.aio import BlobServiceClient
        except ImportError as exc:
            raise ChatHistoryError(
                "Chat artifacts require azure-storage-blob and azure-identity."
            ) from exc

        self._credential = DefaultAzureCredential()
        self._service = BlobServiceClient(
            account_url=self._endpoint,
            credential=self._credential,
        )
        self._container = self._service.get_container_client(self._container_name)
        return self._container

    async def upload(
        self,
        owner_id: str,
        session_id: str,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> dict[str, Any]:
        from azure.storage.blob import ContentSettings

        attachment = _build_attachment(
            owner_id,
            session_id,
            filename,
            content_type,
            content,
        )
        container = await self._get_container()
        blob = container.get_blob_client(attachment["blobName"])
        await blob.upload_blob(
            content,
            overwrite=False,
            content_settings=ContentSettings(content_type=attachment["contentType"]),
        )
        return attachment

    async def download(self, attachment: dict[str, Any]) -> bytes:
        container = await self._get_container()
        blob = container.get_blob_client(attachment["blobName"])
        try:
            stream = await blob.download_blob()
            return await stream.readall()
        except Exception as exc:
            if _is_not_found_error(exc):
                raise ChatHistoryNotFoundError("Attachment content not found.") from exc
            raise

    async def delete(self, attachment: dict[str, Any]) -> None:
        container = await self._get_container()
        blob = container.get_blob_client(attachment["blobName"])
        try:
            await blob.delete_blob(delete_snapshots="include")
        except Exception as exc:
            if not _is_not_found_error(exc):
                raise

    async def touch(self, attachment: dict[str, Any]) -> None:
        container = await self._get_container()
        blob = container.get_blob_client(attachment["blobName"])
        try:
            await blob.set_blob_metadata(metadata={})
        except Exception as exc:
            if _is_not_found_error(exc):
                raise ChatHistoryNotFoundError("Attachment content not found.") from exc
            raise ChatHistoryError("Attachment retention could not be refreshed.") from exc


_history_repository: ChatHistoryRepository | None = None
_artifact_store: ArtifactStore | None = None


def get_chat_history_repository() -> ChatHistoryRepository:
    """Return the configured singleton history repository."""
    global _history_repository
    if _history_repository is not None:
        return _history_repository

    endpoint = os.environ.get("COSMOS_CHAT_ENDPOINT", "").strip()
    mode = os.environ.get("CHAT_HISTORY_STORE", "").strip().lower()
    if mode not in {"cosmos", "memory", "disabled"}:
        raise ChatHistoryError(
            "CHAT_HISTORY_STORE must be cosmos, memory, or disabled."
        )
    if mode == "disabled":
        raise ChatHistoryError("Chat history is disabled in this deployment.")
    if mode == "cosmos" and endpoint:
        _history_repository = CosmosChatHistoryRepository(
            endpoint,
            os.environ.get("COSMOS_CHAT_DATABASE", "planetary-explorer"),
            os.environ.get("COSMOS_CHAT_CONTAINER", "chat-history"),
        )
    elif mode == "cosmos":
        raise ChatHistoryError("COSMOS_CHAT_ENDPOINT is required for Cosmos history.")
    else:
        _history_repository = InMemoryChatHistoryRepository()
    return _history_repository


def get_artifact_store() -> ArtifactStore:
    """Return the configured singleton attachment store."""
    global _artifact_store
    if _artifact_store is not None:
        return _artifact_store

    endpoint = os.environ.get("CHAT_ARTIFACT_BLOB_ENDPOINT", "").strip()
    mode = os.environ.get("CHAT_ARTIFACT_STORE", "").strip().lower()
    if mode not in {"blob", "memory", "disabled"}:
        raise ChatHistoryError(
            "CHAT_ARTIFACT_STORE must be blob, memory, or disabled."
        )
    if mode == "disabled":
        raise ChatHistoryError("Chat artifacts are disabled in this deployment.")
    if mode == "blob" and endpoint:
        _artifact_store = BlobArtifactStore(
            endpoint,
            os.environ.get("CHAT_ARTIFACT_CONTAINER", "chat-artifacts"),
        )
    elif mode == "blob":
        raise ChatHistoryError(
            "CHAT_ARTIFACT_BLOB_ENDPOINT is required for Blob artifacts."
        )
    else:
        _artifact_store = InMemoryArtifactStore()
    return _artifact_store