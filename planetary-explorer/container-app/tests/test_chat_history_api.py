"""Tests for authenticated chat-history and test-bundle endpoints."""

import io
import json
from zipfile import ZipFile

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from chat_history_api import router
from chat_history_store import (
    ChatHistoryError,
    InMemoryArtifactStore,
    InMemoryChatHistoryRepository,
    MAX_EXPORT_BYTES,
)


def _create_client(
    artifacts: InMemoryArtifactStore | None = None,
    repository: InMemoryChatHistoryRepository | None = None,
) -> tuple[TestClient, InMemoryChatHistoryRepository]:
    repository = repository or InMemoryChatHistoryRepository()
    artifact_store = artifacts or InMemoryArtifactStore()
    app = FastAPI()

    @app.middleware("http")
    async def add_test_user(request: Request, call_next):
        request.state.user = {
            "tid": "tenant-1",
            "sub": request.headers.get("X-Test-User", "user-1"),
        }
        return await call_next(request)

    app.include_router(router)
    from chat_history_api import get_artifact_store, get_chat_history_repository

    app.dependency_overrides[get_chat_history_repository] = lambda: repository
    app.dependency_overrides[get_artifact_store] = lambda: artifact_store
    return TestClient(app), repository


def test_given_saved_session_when_another_user_reads_then_returns_not_found() -> None:
    # Arrange
    client, _repository = _create_client()
    payload = {"messages": [{"role": "user", "content": "Show Seattle"}]}
    saved = client.put("/api/chat-history/sessions/web-session-1", json=payload)

    # Act
    other_user = client.get(
        "/api/chat-history/sessions/web-session-1",
        headers={"X-Test-User": "user-2"},
    )

    # Assert
    assert saved.status_code == 200
    assert other_user.status_code == 404


def test_given_session_with_file_when_exported_then_bundle_is_replayable() -> None:
    # Arrange
    client, _repository = _create_client()
    client.put(
        "/api/chat-history/sessions/web-session-1",
        json={
            "messages": [
                {"role": "user", "content": "Test these coordinates"},
                {"role": "assistant", "content": "Loaded 1 row"},
            ],
            "context": {"selectedModel": "gpt-5", "selectedModule": "terrain"},
        },
    )
    upload = client.post(
        "/api/chat-history/sessions/web-session-1/files",
        files={"file": ("coordinates.csv", b"lat,lng\n47.6,-122.3\n", "text/csv")},
    )

    # Act
    exported = client.get("/api/chat-history/sessions/web-session-1/export")
    with ZipFile(io.BytesIO(exported.content)) as bundle:
        names = set(bundle.namelist())
        session = json.loads(bundle.read("session.json"))
        data = bundle.read("files/coordinates.csv")

    # Assert
    assert upload.status_code == 201
    assert exported.status_code == 200
    assert {"session.json", "README.txt", "files/coordinates.csv"} <= names
    assert session["messageCount"] == 2
    assert "ownerId" not in session
    assert "blobName" not in session["attachments"][0]
    assert data == b"lat,lng\n47.6,-122.3\n"


def test_given_session_with_attachment_when_saved_then_retention_is_refreshed() -> None:
    # Arrange
    class TrackingArtifactStore(InMemoryArtifactStore):
        def __init__(self) -> None:
            super().__init__()
            self.touched: list[str] = []

        async def touch(self, attachment: dict) -> None:
            await super().touch(attachment)
            self.touched.append(attachment["id"])

    artifacts = TrackingArtifactStore()
    client, _repository = _create_client(artifacts)
    client.put(
        "/api/chat-history/sessions/web-session-1",
        json={"messages": [{"role": "user", "content": "retain file"}]},
    )
    uploaded = client.post(
        "/api/chat-history/sessions/web-session-1/files",
        files={"file": ("coordinates.csv", b"lat,lng\n", "text/csv")},
    ).json()

    # Act
    saved = client.put(
        "/api/chat-history/sessions/web-session-1",
        json={
            "clientRevision": 2,
            "messages": [{"role": "user", "content": "retain file again"}],
        },
    )

    # Assert
    assert saved.status_code == 200
    assert artifacts.touched == [uploaded["id"]]


def test_given_declared_files_over_limit_when_exported_then_rejects_before_download() -> None:
    # Arrange
    client, repository = _create_client()
    client.put(
        "/api/chat-history/sessions/web-session-1",
        json={"messages": [{"role": "user", "content": "large export"}]},
    )
    document = repository._documents[("tenant-1:user-1", "web-session-1")]
    document["attachments"] = [
        {
            "id": "large-file",
            "name": "large.bin",
            "size": MAX_EXPORT_BYTES + 1,
            "blobName": "missing",
        }
    ]

    # Act
    response = client.get("/api/chat-history/sessions/web-session-1/export")

    # Assert
    assert response.status_code == 413


def test_given_blob_cleanup_failure_when_deleting_then_session_remains_retryable() -> None:
    # Arrange
    class FailingArtifactStore(InMemoryArtifactStore):
        async def delete(self, attachment: dict) -> None:
            raise RuntimeError("storage unavailable")

    client, repository = _create_client(FailingArtifactStore())
    client.put(
        "/api/chat-history/sessions/web-session-1",
        json={"messages": [{"role": "user", "content": "keep me"}]},
    )
    client.post(
        "/api/chat-history/sessions/web-session-1/files",
        files={"file": ("coordinates.csv", b"lat,lng\n", "text/csv")},
    )

    # Act
    deleted = client.delete("/api/chat-history/sessions/web-session-1")

    # Assert
    assert deleted.status_code == 503
    assert client.get("/api/chat-history/sessions/web-session-1").status_code == 200


def test_given_concurrent_attachment_when_deleting_session_then_returns_conflict() -> None:
    # Arrange
    class ConcurrentAttachmentRepository(InMemoryChatHistoryRepository):
        def __init__(self) -> None:
            super().__init__()
            self.add_on_delete = True

        async def delete_session(
            self,
            owner_id: str,
            session_id: str,
            *,
            expected_etag: str | None = None,
        ) -> dict:
            if self.add_on_delete:
                self.add_on_delete = False
                await self.add_attachment(
                    owner_id,
                    session_id,
                    {
                        "id": "concurrent-file",
                        "name": "concurrent.csv",
                        "size": 1,
                        "blobName": "concurrent",
                    },
                )
            return await super().delete_session(
                owner_id,
                session_id,
                expected_etag=expected_etag,
            )

    repository = ConcurrentAttachmentRepository()
    client, _repository = _create_client(repository=repository)
    client.put(
        "/api/chat-history/sessions/web-session-1",
        json={"messages": [{"role": "user", "content": "delete session"}]},
    )

    # Act
    first = client.delete("/api/chat-history/sessions/web-session-1")
    second = client.delete("/api/chat-history/sessions/web-session-1")

    # Assert
    assert first.status_code == 409
    assert second.status_code == 204


def test_given_existing_attachment_when_deleting_then_tombstone_blocks_concurrent_save() -> None:
    # Arrange
    class AutosaveDuringDeletionRepository(InMemoryChatHistoryRepository):
        def __init__(self) -> None:
            super().__init__()
            self.autosave_blocked = False

        async def mark_deleting(
            self,
            owner_id: str,
            session_id: str,
            *,
            expected_etag: str | None = None,
        ) -> dict:
            marked = await super().mark_deleting(
                owner_id,
                session_id,
                expected_etag=expected_etag,
            )
            try:
                await self.upsert_session(
                    owner_id,
                    session_id,
                    {
                        "clientRevision": 2,
                        "messages": [{"role": "user", "content": "late save"}],
                    },
                )
            except ChatHistoryError:
                self.autosave_blocked = True
            return marked

    repository = AutosaveDuringDeletionRepository()
    artifacts = InMemoryArtifactStore()
    client, _repository = _create_client(artifacts, repository)
    client.put(
        "/api/chat-history/sessions/web-session-1",
        json={
            "clientRevision": 1,
            "messages": [{"role": "user", "content": "delete attached"}],
        },
    )
    uploaded = client.post(
        "/api/chat-history/sessions/web-session-1/files",
        files={"file": ("coordinates.csv", b"lat,lng\n", "text/csv")},
    ).json()

    # Act
    deleted = client.delete("/api/chat-history/sessions/web-session-1")

    # Assert
    assert deleted.status_code == 204
    assert repository.autosave_blocked is True
    assert uploaded["id"]
    assert artifacts._files == {}


def test_given_stale_revision_when_saving_then_returns_conflict() -> None:
    # Arrange
    client, _repository = _create_client()
    client.put(
        "/api/chat-history/sessions/web-session-1",
        json={
            "clientRevision": 2,
            "messages": [{"role": "user", "content": "newer"}],
        },
    )

    # Act
    stale = client.put(
        "/api/chat-history/sessions/web-session-1",
        json={
            "clientRevision": 1,
            "messages": [{"role": "user", "content": "older"}],
        },
    )

    # Assert
    assert stale.status_code == 409
    assert client.get("/api/chat-history/sessions/web-session-1").json()["messages"][0][
        "content"
    ] == "newer"


def test_given_metadata_failure_when_deleting_file_then_retry_removes_metadata() -> None:
    # Arrange
    class FailOnceRepository(InMemoryChatHistoryRepository):
        def __init__(self) -> None:
            super().__init__()
            self.fail_once = True

        async def remove_attachment(
            self,
            owner_id: str,
            session_id: str,
            attachment_id: str,
        ) -> dict:
            if self.fail_once:
                self.fail_once = False
                raise ChatHistoryError("Cosmos unavailable")
            return await super().remove_attachment(owner_id, session_id, attachment_id)

    repository = FailOnceRepository()
    client, _repository = _create_client(repository=repository)
    client.put(
        "/api/chat-history/sessions/web-session-1",
        json={"messages": [{"role": "user", "content": "delete file"}]},
    )
    uploaded = client.post(
        "/api/chat-history/sessions/web-session-1/files",
        files={"file": ("coordinates.csv", b"lat,lng\n", "text/csv")},
    ).json()
    route = f"/api/chat-history/sessions/web-session-1/files/{uploaded['id']}"

    # Act
    first = client.delete(route)
    second = client.delete(route)

    # Assert
    assert first.status_code == 503
    assert second.status_code == 204
    session = client.get("/api/chat-history/sessions/web-session-1").json()
    assert session["attachments"] == []