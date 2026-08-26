"""Tests for authenticated chat-history and test-bundle endpoints."""

import io
import json
from zipfile import ZipFile

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from chat_history_api import router
from chat_history_store import InMemoryArtifactStore, InMemoryChatHistoryRepository


def _create_client() -> TestClient:
    repository = InMemoryChatHistoryRepository()
    artifacts = InMemoryArtifactStore()
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
    app.dependency_overrides[get_artifact_store] = lambda: artifacts
    return TestClient(app)


def test_given_saved_session_when_another_user_reads_then_returns_not_found() -> None:
    # Arrange
    client = _create_client()
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
    client = _create_client()
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