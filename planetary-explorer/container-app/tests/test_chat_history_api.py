"""Tests for authenticated chat-history and test-bundle endpoints."""

import copy
import io
import json
from zipfile import ZipFile

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from chat_history_api import router
import chat_history_api
from chat_history_store import (
    ChatHistoryNotFoundError,
    InMemoryArtifactStore,
    InMemoryChatHistoryRepository,
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


def test_given_application_routes_when_registered_then_history_router_is_included_once() -> None:
    # Arrange
    import fastapi_app

    # Act
    matching_routes = [
        route
        for route in fastapi_app.app.routes
        if getattr(route, "path", None) == "/api/chat-history/sessions"
    ]

    # Assert
    assert len(matching_routes) == 1


def test_given_saved_session_when_another_user_reads_then_returns_not_found() -> None:
    # Arrange
    client, _repository = _create_client()
    payload = {
        "expectedRevision": 0,
        "mutationId": "isolation-save",
        "messages": [{"role": "user", "content": "Show Seattle"}],
    }
    saved = client.put("/api/chat-history/sessions/web-session-1", json=payload)

    # Act
    other_user = client.get(
        "/api/chat-history/sessions/web-session-1",
        headers={"X-Test-User": "user-2"},
    )

    # Assert
    assert saved.status_code == 200
    assert other_user.status_code == 404


def test_given_non_object_json_when_saving_then_returns_bad_request() -> None:
    # Arrange
    client, _repository = _create_client()

    # Act
    response = client.put("/api/chat-history/sessions/web-session-1", json=[])

    # Assert
    assert response.status_code == 400
    assert response.json()["detail"] == "Session body must be a JSON object."


def test_given_malformed_expected_revision_when_saving_then_returns_bad_request() -> None:
    # Arrange
    client, _repository = _create_client()

    for expected_revision in (True, "1"):
        # Act
        response = client.put(
            "/api/chat-history/sessions/web-session-1",
            json={
                "expectedRevision": expected_revision,
                "mutationId": "malformed-revision-save",
                "messages": [{"role": "user", "content": "Test"}],
            },
        )

        # Assert
        assert response.status_code == 400
        assert response.json()["detail"] == (
            "expectedRevision must be a non-negative integer."
        )


def test_given_session_with_file_when_exported_then_bundle_is_replayable() -> None:
    # Arrange
    client, _repository = _create_client()
    client.put(
        "/api/chat-history/sessions/web-session-1",
        json={
            "expectedRevision": 0,
            "mutationId": "export-save",
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


def test_given_attachment_metadata_committed_when_response_is_lost_then_blob_is_retained() -> None:
    # Arrange
    class AmbiguousAttachmentRepository(InMemoryChatHistoryRepository):
        async def add_attachment(
            self,
            owner_id: str,
            session_id: str,
            attachment: dict,
        ) -> dict:
            await super().add_attachment(owner_id, session_id, attachment)
            raise RuntimeError("metadata response lost")

    artifacts = InMemoryArtifactStore()
    repository = AmbiguousAttachmentRepository()
    client, _repository = _create_client(artifacts, repository)
    client.put(
        "/api/chat-history/sessions/web-session-1",
        json={
            "expectedRevision": 0,
            "mutationId": "ambiguous-file-save",
            "messages": [{"role": "user", "content": "retain the file"}],
        },
    )

    # Act
    uploaded = client.post(
        "/api/chat-history/sessions/web-session-1/files",
        files={"file": ("coordinates.csv", b"lat,lng\n47.6,-122.3\n", "text/csv")},
    )
    attachment = uploaded.json()
    downloaded = client.get(
        f"/api/chat-history/sessions/web-session-1/files/{attachment['id']}"
    )

    # Assert
    assert uploaded.status_code == 201
    assert downloaded.status_code == 200
    assert downloaded.content == b"lat,lng\n47.6,-122.3\n"


def test_given_ambiguous_upload_and_stale_reconciliation_then_blob_is_not_deleted() -> None:
    # Arrange
    class StaleReconciliationRepository(InMemoryChatHistoryRepository):
        def __init__(self) -> None:
            super().__init__()
            self.stale_document: dict | None = None
            self.return_stale_once = False

        async def add_attachment(
            self,
            owner_id: str,
            session_id: str,
            attachment: dict,
        ) -> dict:
            self.stale_document = await super().get_session(owner_id, session_id)
            await super().add_attachment(owner_id, session_id, attachment)
            self.return_stale_once = True
            raise RuntimeError("metadata response lost")

        async def get_session(self, owner_id: str, session_id: str) -> dict:
            if self.return_stale_once and self.stale_document is not None:
                self.return_stale_once = False
                return copy.deepcopy(self.stale_document)
            return await super().get_session(owner_id, session_id)

    class TrackingArtifactStore(InMemoryArtifactStore):
        def __init__(self) -> None:
            super().__init__()
            self.deleted: list[str] = []

        async def delete(self, attachment: dict) -> None:
            self.deleted.append(attachment["id"])
            await super().delete(attachment)

    artifacts = TrackingArtifactStore()
    repository = StaleReconciliationRepository()
    client, _repository = _create_client(artifacts, repository)
    client.put(
        "/api/chat-history/sessions/web-session-1",
        json={
            "expectedRevision": 0,
            "mutationId": "stale-file-save",
            "messages": [{"role": "user", "content": "retain ambiguous upload"}],
        },
    )

    # Act
    upload = client.post(
        "/api/chat-history/sessions/web-session-1/files",
        files={"file": ("coordinates.csv", b"lat,lng\n47.6,-122.3\n", "text/csv")},
    )
    session = client.get("/api/chat-history/sessions/web-session-1").json()
    attachment = session["attachments"][0]
    downloaded = client.get(
        f"/api/chat-history/sessions/web-session-1/files/{attachment['id']}"
    )

    # Assert
    assert upload.status_code == 503
    assert artifacts.deleted == []
    assert downloaded.status_code == 200
    assert downloaded.content == b"lat,lng\n47.6,-122.3\n"


def test_given_session_deleted_during_upload_then_orphaned_blob_is_removed() -> None:
    # Arrange
    class DeletedSessionRepository(InMemoryChatHistoryRepository):
        async def add_attachment(
            self,
            owner_id: str,
            session_id: str,
            attachment: dict,
        ) -> dict:
            self._documents.pop((owner_id, session_id), None)
            raise ChatHistoryNotFoundError("Chat session not found.")

    class TrackingArtifactStore(InMemoryArtifactStore):
        def __init__(self) -> None:
            super().__init__()
            self.deleted: list[str] = []

        async def delete(self, attachment: dict) -> None:
            self.deleted.append(attachment["id"])
            await super().delete(attachment)

    artifacts = TrackingArtifactStore()
    client, _repository = _create_client(artifacts, DeletedSessionRepository())
    client.put(
        "/api/chat-history/sessions/web-session-1",
        json={
            "expectedRevision": 0,
            "mutationId": "deleted-file-save",
            "messages": [{"role": "user", "content": "delete during upload"}],
        },
    )

    # Act
    upload = client.post(
        "/api/chat-history/sessions/web-session-1/files",
        files={"file": ("coordinates.csv", b"lat,lng\n", "text/csv")},
    )

    # Assert
    assert upload.status_code == 404
    assert len(artifacts.deleted) == 1
    assert artifacts._files == {}


def test_given_blob_cleanup_failure_when_deleting_then_session_remains_retryable() -> None:
    # Arrange
    class FailingArtifactStore(InMemoryArtifactStore):
        async def delete(self, attachment: dict) -> None:
            raise RuntimeError("storage unavailable")

    client, repository = _create_client(FailingArtifactStore())
    client.put(
        "/api/chat-history/sessions/web-session-1",
        json={
            "expectedRevision": 0,
            "mutationId": "session-delete-save",
            "messages": [{"role": "user", "content": "keep me"}],
        },
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


def test_given_blob_delete_failure_when_deleting_file_then_metadata_remains_retryable() -> None:
    # Arrange
    class FailingArtifactStore(InMemoryArtifactStore):
        async def delete(self, attachment: dict) -> None:
            raise RuntimeError("storage unavailable")

    client, _repository = _create_client(FailingArtifactStore())
    client.put(
        "/api/chat-history/sessions/web-session-1",
        json={
            "expectedRevision": 0,
            "mutationId": "file-delete-save",
            "messages": [{"role": "user", "content": "keep file metadata"}],
        },
    )
    uploaded = client.post(
        "/api/chat-history/sessions/web-session-1/files",
        files={"file": ("coordinates.csv", b"lat,lng\n", "text/csv")},
    ).json()

    # Act
    deleted = client.delete(
        f"/api/chat-history/sessions/web-session-1/files/{uploaded['id']}"
    )

    # Assert
    assert deleted.status_code == 503
    session = client.get("/api/chat-history/sessions/web-session-1").json()
    assert session["attachments"][0]["id"] == uploaded["id"]


def test_given_active_session_with_file_when_saved_then_attachment_is_renewed() -> None:
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
        json={
            "expectedRevision": 0,
            "mutationId": "renew-initial-save",
            "messages": [{"role": "user", "content": "initial"}],
        },
    )
    uploaded = client.post(
        "/api/chat-history/sessions/web-session-1/files",
        files={"file": ("coordinates.csv", b"lat,lng\n", "text/csv")},
    ).json()

    # Act
    saved = client.put(
        "/api/chat-history/sessions/web-session-1",
        json={
            "expectedRevision": 1,
            "mutationId": "renew-continuation-save",
            "messages": [{"role": "user", "content": "continued"}],
        },
    )

    # Assert
    assert saved.status_code == 200
    assert artifacts.touched == [uploaded["id"]]


def test_given_committed_mutation_when_retried_then_returns_same_revision() -> None:
    # Arrange
    client, _repository = _create_client()
    payload = {
        "expectedRevision": 0,
        "mutationId": "ambiguous-success-save",
        "messages": [{"role": "user", "content": "save exactly once"}],
    }

    # Act
    first = client.put("/api/chat-history/sessions/web-session-1", json=payload)
    replay = client.put("/api/chat-history/sessions/web-session-1", json=payload)

    # Assert
    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["revision"] == first.json()["revision"] == 1


def test_given_oversized_attachments_when_exporting_then_rejects_before_download(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setattr(chat_history_api, "MAX_EXPORT_BYTES", 10)
    client, _repository = _create_client()
    client.put(
        "/api/chat-history/sessions/web-session-1",
        json={
            "expectedRevision": 0,
            "mutationId": "oversized-export-save",
            "messages": [{"role": "user", "content": "large export"}],
        },
    )
    client.post(
        "/api/chat-history/sessions/web-session-1/files",
        files={"file": ("coordinates.csv", b"12345678901", "text/csv")},
    )

    # Act
    exported = client.get("/api/chat-history/sessions/web-session-1/export")

    # Assert
    assert exported.status_code == 413
    assert exported.json()["detail"] == "Test bundle exceeds the 100 MB export limit."