"""Owner-filtered AI Search recall backed by canonical chat-history documents."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from typing import Any

from chat_history_store import (
    MAX_MESSAGES,
    ChatHistoryError,
    ChatHistoryNotFoundError,
    ChatHistoryRepository,
    opaque_owner_key,
    sanitize_value,
    validate_session_id,
)
from connectors.ai_search import AiSearchClient


logger = logging.getLogger(__name__)
MAX_MEMORY_HITS = 4
MAX_INDEX_CONTENT_CHARS = 6000
MAX_FALLBACK_SESSIONS = 12
MEMORY_TIMEOUT_SECONDS = 3.0


def _document_key(owner_id: str, session_id: str, turn: int) -> str:
    return hashlib.sha256(f"{owner_id}\0{session_id}\0{turn}".encode()).hexdigest()


def _turn_fingerprint(role: str, content: str) -> str:
    return hashlib.sha256(f"{role}\0{content}".encode()).hexdigest()


def build_memory_documents(owner_id: str, session: dict[str, Any]) -> list[dict[str, Any]]:
    """Index sanitized text only; never index attachments, screenshots, or tool payloads."""
    if session.get("ownerId") != owner_id or session.get("_deleting") or session.get("memoryEnabled") is False:
        return []
    session_id = validate_session_id(session["sessionId"])
    documents: list[dict[str, Any]] = []
    for position, turn in enumerate(session.get("messages", [])[:MAX_MESSAGES]):
        role = turn.get("role")
        if role not in {"user", "assistant"} or not isinstance(turn.get("content"), str):
            continue
        content = sanitize_value(turn["content"])[:MAX_INDEX_CONTENT_CHARS]
        if not content.strip():
            continue
        documents.append({
            "id": _document_key(owner_id, session_id, position),
            "ownerKey": opaque_owner_key(owner_id),
            "sessionId": session_id,
            "turn": position,
            "role": role,
            "title": sanitize_value(str(session.get("title") or "Saved chat"))[:96],
            "content": content,
            "fingerprint": _turn_fingerprint(role, content),
            "updatedAt": session["updatedAt"],
        })
    return documents


def create_memory_index_schema(name: str) -> Any:
    """Build the dedicated memory index, including optional semantic ranking."""
    from azure.search.documents.indexes.models import (
        SearchFieldDataType,
        SearchIndex,
        SearchableField,
        SemanticConfiguration,
        SemanticField,
        SemanticPrioritizedFields,
        SemanticSearch,
        SimpleField,
    )

    return SearchIndex(
        name=name,
        fields=[
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(name="ownerKey", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="sessionId", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="turn", type=SearchFieldDataType.Int32),
            SimpleField(name="role", type=SearchFieldDataType.String),
            SearchableField(name="title", type=SearchFieldDataType.String),
            SearchableField(name="content", type=SearchFieldDataType.String),
            SimpleField(name="fingerprint", type=SearchFieldDataType.String),
            SimpleField(name="updatedAt", type=SearchFieldDataType.DateTimeOffset, sortable=True),
        ],
        semantic_search=SemanticSearch(configurations=[
            SemanticConfiguration(
                name="chat-memory",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"),
                    content_fields=[SemanticField(field_name="content")],
                ),
            ),
        ]),
    )


class ChatMemorySearch:
    """Dedicated Search index with mandatory owner filters and deterministic keys."""

    def __init__(self, client: AiSearchClient) -> None:
        self._client = client

    @classmethod
    def from_env(cls) -> ChatMemorySearch | None:
        """Use the existing Search service only when a memory index is configured."""
        index_name = os.getenv("CHAT_MEMORY_SEARCH_INDEX", "").strip()
        if not index_name:
            return None
        client = AiSearchClient.from_env(
            index=index_name, endpoint=os.getenv("CHAT_MEMORY_SEARCH_ENDPOINT") or None,
        )
        return cls(client) if client else None

    async def sync_session(self, owner_id: str, session: dict[str, Any]) -> None:
        """Replace a session's indexed turns and remove obsolete turn keys."""
        session_id = validate_session_id(session["sessionId"])
        documents = build_memory_documents(owner_id, session)
        await self._client.upload_documents(documents)
        retained = {document["id"] for document in documents}
        await self._client.delete_documents([
            {"id": key}
            for position in range(MAX_MESSAGES)
            if (key := _document_key(owner_id, session_id, position)) not in retained
        ])

    async def delete_session(self, owner_id: str, session_id: str) -> None:
        """Remove only this owner's deterministic session keys."""
        validate_session_id(session_id)
        await self._client.delete_documents([
            {"id": _document_key(owner_id, session_id, position)}
            for position in range(MAX_MESSAGES)
        ])

    async def search(self, owner_id: str, session_id: str, question: str) -> list[dict[str, Any]]:
        """Retrieve candidate identities; content is read again from the owning repository."""
        if not owner_id:
            return []
        query = " ".join(re.findall(r"[\w.-]+", sanitize_value(question)))[:1000]
        if not query:
            return []
        escaped_session = session_id.replace("'", "''")
        return await self._client.search(
            query,
            top=MAX_MEMORY_HITS * 3,
            filter=f"ownerKey eq '{opaque_owner_key(owner_id)}' and sessionId ne '{escaped_session}'",
            select=["ownerKey", "sessionId", "turn", "fingerprint"],
            search_fields=["content", "title"],
            semantic_configuration=os.getenv("CHAT_MEMORY_SEMANTIC_CONFIGURATION") or None,
        )

    async def aclose(self) -> None:
        """Close Search transports and identity credentials."""
        await self._client.aclose()


async def recall_saved_context(
    owner_id: str,
    session_id: str,
    question: str,
    repository: ChatHistoryRepository,
    *,
    index: ChatMemorySearch | None = None,
) -> dict[str, Any]:
    """Recall owned, still-current turns, with a bounded recent-history fallback."""
    from chat_memory import _terms

    sessions: dict[str, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []
    provider = "history"
    if index:
        try:
            async with asyncio.timeout(MEMORY_TIMEOUT_SECONDS):
                candidates = await index.search(owner_id, session_id, question)
            provider = "azure-search"
        except Exception as exc:
            logger.warning("[ChatMemory] Search recall unavailable: %s", type(exc).__name__)

    if provider == "history" or not candidates:
        provider = "history"
        terms = _terms(question)
        explicit_recall = bool(re.search(
            r"\b(?:last|previous|earlier|other)\b.{0,30}\b(?:chat|conversation|session|time)\b",
            question,
            re.IGNORECASE,
        ))
        summaries = (await repository.list_sessions(owner_id))[:MAX_FALLBACK_SESSIONS]
        for summary in summaries:
            candidate_id = summary["sessionId"]
            if candidate_id == session_id or summary.get("memoryEnabled") is False:
                continue
            try:
                document = await repository.get_session(owner_id, candidate_id)
            except ChatHistoryNotFoundError:
                continue
            sessions[candidate_id] = document
            for candidate in build_memory_documents(owner_id, document):
                score = len(terms & _terms(candidate["content"]))
                if explicit_recall and len(sessions) == 1:
                    score += 1
                if score:
                    candidates.append({**candidate, "score": score})
        candidates.sort(key=lambda candidate: (candidate["score"], candidate["updatedAt"]), reverse=True)

    recalled: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for candidate in candidates[:MAX_MEMORY_HITS * 3]:
        candidate_id = candidate.get("sessionId")
        position = candidate.get("turn")
        if (
            candidate.get("ownerKey") != opaque_owner_key(owner_id)
            or not isinstance(candidate_id, str)
            or candidate_id == session_id
            or isinstance(position, bool)
            or not isinstance(position, int)
            or position < 0
            or (candidate_id, position) in seen
        ):
            continue
        if candidate_id not in sessions:
            try:
                sessions[candidate_id] = await repository.get_session(owner_id, candidate_id)
            except ChatHistoryNotFoundError:
                continue
        canonical = sessions[candidate_id]
        current = next(
            (turn for turn in build_memory_documents(owner_id, canonical) if turn["turn"] == position),
            None,
        )
        if current is None or current["fingerprint"] != candidate.get("fingerprint"):
            continue
        recalled.append({
            key: current[key]
            for key in ("sessionId", "turn", "role", "title", "content", "updatedAt")
        })
        seen.add((candidate_id, position))
        if len(recalled) >= MAX_MEMORY_HITS:
            break
    return {"provider": provider, "memories": recalled}


async def sync_saved_memory(
    owner_id: str, session_id: str, repository: ChatHistoryRepository,
) -> None:
    """Best-effort indexing must not turn a committed history save into a failed save."""
    index = None
    try:
        index = ChatMemorySearch.from_env()
        if index is None:
            return
        async with asyncio.timeout(MEMORY_TIMEOUT_SECONDS):
            try:
                session = await repository.get_session(owner_id, session_id)
                await index.sync_session(owner_id, session)
                latest = await repository.get_session(owner_id, session_id)
                if latest.get("_etag") != session.get("_etag"):
                    await index.sync_session(owner_id, latest)
            except ChatHistoryNotFoundError:
                await index.delete_session(owner_id, session_id)
    except Exception as exc:
        logger.warning("[ChatMemory] Index sync deferred until next save: %s", type(exc).__name__)
    finally:
        if index:
            try:
                await index.aclose()
            except Exception as exc:
                logger.warning("[ChatMemory] Search close failed: %s", type(exc).__name__)


async def delete_saved_memory(owner_id: str, session_id: str) -> None:
    """Keep failed index deletions retryable through the history tombstone."""
    index = ChatMemorySearch.from_env()
    if index is None:
        return
    try:
        async with asyncio.timeout(MEMORY_TIMEOUT_SECONDS):
            await index.delete_session(owner_id, session_id)
    except Exception as exc:
        raise ChatHistoryError("Saved memory could not be deleted; retry the request.") from exc
    finally:
        await index.aclose()