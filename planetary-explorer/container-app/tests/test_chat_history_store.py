"""Tests for owner-isolated chat history persistence."""

import pytest

from chat_history_store import (
    BlobArtifactStore,
    InMemoryArtifactStore,
    InMemoryChatHistoryRepository,
    normalize_session_document,
    public_session_document,
)


class _FakeBlob:
    def __init__(self) -> None:
        self.upload: dict | None = None

    async def upload_blob(self, content: bytes, **kwargs) -> None:
        self.upload = {"content": content, **kwargs}


class _FakeBlobContainer:
    def __init__(self) -> None:
        self.blob = _FakeBlob()

    def get_blob_client(self, _blob_name: str) -> _FakeBlob:
        return self.blob


@pytest.mark.asyncio
async def test_given_same_session_id_when_owners_differ_then_history_is_isolated() -> None:
    # Arrange
    repository = InMemoryChatHistoryRepository()

    # Act
    await repository.upsert_session(
        "tenant:user-1",
        "web-session-1",
        {"messages": [{"role": "user", "content": "first"}]},
    )
    await repository.upsert_session(
        "tenant:user-2",
        "web-session-1",
        {"messages": [{"role": "user", "content": "second"}]},
    )

    # Assert
    first = await repository.get_session("tenant:user-1", "web-session-1")
    second = await repository.get_session("tenant:user-2", "web-session-1")
    assert first["messages"][0]["content"] == "first"
    assert second["messages"][0]["content"] == "second"


def test_given_sensitive_context_when_normalized_then_secrets_and_large_data_are_removed() -> None:
    # Arrange
    signed_url = "https://example.blob.core.windows.net/file.tif?sv=1&sig=secret"
    payload = {
        "messages": [
            {
                "role": "assistant",
                "content": f"Download {signed_url}",
                "toolTrace": [{"args": {
                    "accessToken": "secret",
                    "authorization": "Bearer abc.def.ghi",
                    "artifact_uri": signed_url,
                }}],
            }
        ],
        "context": {
            "selectedModel": "gpt-5",
            "map": {
                "imagery_base64": "a" * 1000,
                "stac_items": [{"assets": {"data": {"href": signed_url}}}],
                "bounds": {"north": 1},
            },
        },
    }

    # Act
    document = normalize_session_document("tenant:user-1", "web-session-1", payload)
    public = public_session_document(document)

    # Assert
    assert public["messages"][0]["content"].endswith("?<redacted>")
    assert "accessToken" not in public["messages"][0]["toolTrace"][0]["args"]
    assert "authorization" not in public["messages"][0]["toolTrace"][0]["args"]
    assert public["context"]["map"] == {"bounds": {"north": 1}}
    assert "ownerId" not in public


def test_given_chat_legend_when_normalized_then_colour_explanation_is_preserved() -> None:
    # Arrange
    legend = {
        "title": "Facility risk severity",
        "items": [
            {"color": "#22c55e", "label": "Low", "description": "Routine monitoring"},
            {"color": "#dc2626", "label": "Severe", "description": "Immediate response"},
        ],
        "note": "Marker numbers show the overall risk score.",
    }
    payload = {
        "messages": [
            {
                "role": "assistant",
                "content": "Two facilities are at risk.",
                "legend": legend,
            }
        ]
    }

    # Act
    document = normalize_session_document("tenant:user-1", "web-session-1", payload)

    # Assert
    assert document["messages"][0]["legend"] == legend


@pytest.mark.asyncio
async def test_given_data_file_when_uploaded_then_manifest_and_bytes_round_trip() -> None:
    # Arrange
    store = InMemoryArtifactStore()
    content = b"latitude,longitude\n47.6,-122.3\n"

    # Act
    attachment = await store.upload(
        "tenant:user-1",
        "web-session-1",
        "test-data.csv",
        "text/csv",
        content,
    )
    downloaded = await store.download(attachment)

    # Assert
    assert attachment["name"] == "test-data.csv"
    assert attachment["size"] == len(content)
    assert downloaded == content


@pytest.mark.asyncio
async def test_given_blob_upload_when_content_type_supplied_then_uses_content_settings() -> None:
    # Arrange
    container = _FakeBlobContainer()
    store = BlobArtifactStore(
        "https://storage.example",
        "chat-artifacts",
        container_client=container,
    )

    # Act
    await store.upload(
        "tenant:user-1",
        "web-session-1",
        "coordinates.csv",
        "text/csv",
        b"lat,lng\n",
    )

    # Assert
    assert container.blob.upload is not None
    assert container.blob.upload["content_settings"].content_type == "text/csv"