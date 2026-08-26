"""Authenticated chat-history, attachment, and test-bundle API routes."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from tempfile import SpooledTemporaryFile
from typing import Any, Awaitable, TypeVar
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse

from chat_history_store import (
    MAX_ATTACHMENT_BYTES,
    MAX_EXPORT_BYTES,
    ArtifactStore,
    ChatHistoryConflictError,
    ChatHistoryError,
    ChatHistoryNotFoundError,
    ChatHistoryRepository,
    ChatHistoryValidationError,
    get_artifact_store,
    get_chat_history_repository,
    public_session_document,
    session_summary,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat-history", tags=["chat-history"])
_Result = TypeVar("_Result")


def get_request_owner(request: Request) -> str:
    """Resolve the stable owner only from middleware-validated claims."""
    user = getattr(request.state, "user", {}) or {}
    subject = (
        user.get("oid")
        or user.get("sub")
        or user.get("http://schemas.microsoft.com/identity/claims/objectidentifier")
    )
    tenant = user.get("tid")
    if subject:
        return f"{tenant}:{subject}" if tenant else str(subject)
    if os.environ.get("CHAT_HISTORY_ALLOW_ANONYMOUS", "false").casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return "local-development"
    raise HTTPException(status_code=401, detail="Sign in to use chat history.")


async def _history_call(operation: Awaitable[_Result]) -> _Result:
    try:
        return await operation
    except ChatHistoryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChatHistoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatHistoryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ChatHistoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _find_attachment(document: dict[str, Any], attachment_id: str) -> dict[str, Any]:
    attachment = next(
        (
            item
            for item in document.get("attachments", [])
            if item.get("id") == attachment_id
        ),
        None,
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    return attachment


def _download_headers(filename: str) -> dict[str, str]:
    return {
        "Cache-Control": "private, no-store",
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Content-Type-Options": "nosniff",
    }


@router.get("/sessions")
async def list_chat_sessions(
    owner_id: str = Depends(get_request_owner),
    repository: ChatHistoryRepository = Depends(get_chat_history_repository),
) -> dict[str, Any]:
    sessions = await _history_call(repository.list_sessions(owner_id))
    return {"sessions": sessions}


@router.get("/sessions/{session_id}")
async def get_chat_session(
    session_id: str,
    owner_id: str = Depends(get_request_owner),
    repository: ChatHistoryRepository = Depends(get_chat_history_repository),
) -> dict[str, Any]:
    document = await _history_call(repository.get_session(owner_id, session_id))
    return public_session_document(document)


@router.put("/sessions/{session_id}")
async def save_chat_session(
    session_id: str,
    request: Request,
    owner_id: str = Depends(get_request_owner),
    repository: ChatHistoryRepository = Depends(get_chat_history_repository),
    artifacts: ArtifactStore = Depends(get_artifact_store),
) -> dict[str, Any]:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Session body must be valid JSON.") from exc
    document = await _history_call(
        repository.upsert_session(owner_id, session_id, payload)
    )
    for attachment in document.get("attachments", []):
        await _history_call(artifacts.touch(attachment))
    return public_session_document(document)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_chat_session(
    session_id: str,
    owner_id: str = Depends(get_request_owner),
    repository: ChatHistoryRepository = Depends(get_chat_history_repository),
    artifacts: ArtifactStore = Depends(get_artifact_store),
) -> Response:
    document = await _history_call(repository.get_session(owner_id, session_id))
    if document.get("deleting") is not True:
        document = await _history_call(
            repository.mark_deleting(
                owner_id,
                session_id,
                expected_etag=document.get("_etag"),
            )
        )
    cleanup_failures: list[str] = []
    for attachment in document.get("attachments", []):
        try:
            await artifacts.delete(attachment)
        except Exception:
            cleanup_failures.append(str(attachment.get("id") or "unknown"))
            logger.exception(
                "[ChatHistory] orphan cleanup failed for attachment %s",
                attachment.get("id"),
            )
    if cleanup_failures:
        raise HTTPException(
            status_code=503,
            detail="Session files could not be deleted; retry the request.",
        )
    await _history_call(
        repository.delete_session(
            owner_id,
            session_id,
            expected_etag=document.get("_etag"),
        )
    )
    return Response(status_code=204)


@router.post("/sessions/{session_id}/files", status_code=201)
async def upload_chat_file(
    session_id: str,
    file: UploadFile = File(...),
    owner_id: str = Depends(get_request_owner),
    repository: ChatHistoryRepository = Depends(get_chat_history_repository),
    artifacts: ArtifactStore = Depends(get_artifact_store),
) -> dict[str, Any]:
    await _history_call(repository.get_session(owner_id, session_id))
    content = bytearray()
    while chunk := await file.read(1024 * 1024):
        content.extend(chunk)
        if len(content) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds the 25 MB upload limit.")

    attachment = await _history_call(
        artifacts.upload(
            owner_id,
            session_id,
            file.filename or "data.bin",
            file.content_type or "application/octet-stream",
            bytes(content),
        )
    )
    try:
        document = await _history_call(
            repository.add_attachment(owner_id, session_id, attachment)
        )
    except Exception:
        await artifacts.delete(attachment)
        raise
    return session_summary(document)["attachments"][-1]


@router.get("/sessions/{session_id}/files/{attachment_id}")
async def download_chat_file(
    session_id: str,
    attachment_id: str,
    owner_id: str = Depends(get_request_owner),
    repository: ChatHistoryRepository = Depends(get_chat_history_repository),
    artifacts: ArtifactStore = Depends(get_artifact_store),
) -> Response:
    document = await _history_call(repository.get_session(owner_id, session_id))
    attachment = _find_attachment(document, attachment_id)
    content = await _history_call(artifacts.download(attachment))
    return Response(
        content=content,
        media_type=attachment.get("contentType") or "application/octet-stream",
        headers=_download_headers(attachment["name"]),
    )


@router.delete("/sessions/{session_id}/files/{attachment_id}", status_code=204)
async def delete_chat_file(
    session_id: str,
    attachment_id: str,
    owner_id: str = Depends(get_request_owner),
    repository: ChatHistoryRepository = Depends(get_chat_history_repository),
    artifacts: ArtifactStore = Depends(get_artifact_store),
) -> Response:
    document = await _history_call(repository.get_session(owner_id, session_id))
    attachment = _find_attachment(document, attachment_id)
    await _history_call(artifacts.delete(attachment))
    await _history_call(
        repository.remove_attachment(owner_id, session_id, attachment_id)
    )
    return Response(status_code=204)


def _test_bundle_readme(document: dict[str, Any]) -> str:
    context = document.get("context", {})
    lines = [
        "Planetary Explorer chat test bundle",
        "",
        f"Session: {document.get('sessionId', '')}",
        f"Saved: {document.get('updatedAt', '')}",
        f"Messages: {document.get('messageCount', 0)}",
        f"Model: {context.get('selectedModel') or 'deployment default'}",
        f"Module: {context.get('selectedModule') or 'standard chat'}",
        "",
        "Replay:",
        "1. Open session.json and review context and messages.",
        "2. Load any files/ entries into the system under test.",
        "3. Replay user-role messages in timestamp order.",
        "4. Compare answers and tool traces with the saved assistant turns.",
        "",
        "Secrets, screenshots, signed URL queries, and raw storage paths are omitted.",
    ]
    return "\n".join(lines)


@router.get("/sessions/{session_id}/export")
async def export_chat_session(
    session_id: str,
    owner_id: str = Depends(get_request_owner),
    repository: ChatHistoryRepository = Depends(get_chat_history_repository),
    artifacts: ArtifactStore = Depends(get_artifact_store),
) -> StreamingResponse:
    document = await _history_call(repository.get_session(owner_id, session_id))
    exported = public_session_document(document)
    declared_size = sum(
        max(0, int(attachment.get("size") or 0))
        for attachment in document.get("attachments", [])
    )
    if declared_size > MAX_EXPORT_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Session files exceed the 100 MB export limit.",
        )
    archive = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    try:
        with ZipFile(archive, mode="w", compression=ZIP_DEFLATED) as bundle:
            await asyncio.to_thread(
                bundle.writestr,
                "session.json",
                json.dumps(exported, indent=2, ensure_ascii=True).encode("utf-8"),
            )
            await asyncio.to_thread(
                bundle.writestr,
                "README.txt",
                _test_bundle_readme(exported).encode("utf-8"),
            )
            used_names: set[str] = set()
            actual_size = 0
            for attachment in document.get("attachments", []):
                content = await _history_call(artifacts.download(attachment))
                actual_size += len(content)
                if actual_size > MAX_EXPORT_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Session files exceed the 100 MB export limit.",
                    )
                filename = attachment["name"]
                archive_name = f"files/{filename}"
                if archive_name in used_names:
                    archive_name = f"files/{attachment['id']}-{filename}"
                used_names.add(archive_name)
                await asyncio.to_thread(bundle.writestr, archive_name, content)
    except Exception:
        archive.close()
        raise
    archive.seek(0)

    def stream_archive():
        try:
            while chunk := archive.read(1024 * 1024):
                yield chunk
        finally:
            archive.close()

    return StreamingResponse(
        stream_archive(),
        media_type="application/zip",
        headers=_download_headers(f"planetary-explorer-{session_id}.zip"),
    )