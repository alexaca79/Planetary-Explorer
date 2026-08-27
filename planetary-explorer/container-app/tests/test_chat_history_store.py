"""Tests for owner-isolated chat history persistence."""

import copy

import pytest

import chat_history_store
from chat_history_store import (
    BlobArtifactStore,
    ChatHistoryConflictError,
    ChatHistoryError,
    CosmosChatHistoryRepository,
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


class _CosmosStatusError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _ConflictingCosmosContainer:
    def __init__(self) -> None:
        self.document = normalize_session_document(
            "tenant:user-1",
            "web-session-1",
            {"messages": [{"role": "user", "content": "old"}]},
        )
        self.document["_etag"] = "etag-1"
        self.replace_calls = 0

    async def read_item(self, *, item: str, partition_key: str) -> dict:
        assert item == "web-session-1"
        assert partition_key == "tenant:user-1"
        return copy.deepcopy(self.document)

    async def replace_item(self, *, item: str, body: dict, **_kwargs) -> dict:
        self.replace_calls += 1
        if self.replace_calls == 1:
            self.document["attachments"] = [{"id": "concurrent-file"}]
            self.document["_etag"] = "etag-2"
            raise _CosmosStatusError(412)
        self.document = copy.deepcopy(body)
        self.document["_etag"] = "etag-3"
        return copy.deepcopy(self.document)


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


@pytest.mark.asyncio
async def test_given_cosmos_etag_conflict_when_saving_then_retries_without_losing_attachments() -> None:
    # Arrange
    container = _ConflictingCosmosContainer()
    repository = CosmosChatHistoryRepository(
        "https://cosmos.example",
        "planetary-explorer",
        "chat-history",
        container_client=container,
    )

    # Act
    saved = await repository.upsert_session(
        "tenant:user-1",
        "web-session-1",
        {"messages": [{"role": "user", "content": "new"}]},
    )

    # Assert
    assert container.replace_calls == 2
    assert saved["messages"][0]["content"] == "new"
    assert saved["attachments"] == [{"id": "concurrent-file"}]


@pytest.mark.asyncio
async def test_given_older_revision_when_cosmos_retries_then_rejects_stale_snapshot() -> None:
    # Arrange
    container = _ConflictingCosmosContainer()
    container.document["clientRevision"] = 2
    repository = CosmosChatHistoryRepository(
        "https://cosmos.example",
        "planetary-explorer",
        "chat-history",
        container_client=container,
    )

    # Act & Assert
    with pytest.raises(ChatHistoryConflictError, match="newer chat snapshot"):
        await repository.upsert_session(
            "tenant:user-1",
            "web-session-1",
            {
                "clientRevision": 1,
                "messages": [{"role": "user", "content": "stale"}],
            },
        )
    assert container.replace_calls == 0


def test_given_disabled_modes_with_endpoints_when_resolved_then_stores_remain_disabled(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setattr(chat_history_store, "_history_repository", None)
    monkeypatch.setattr(chat_history_store, "_artifact_store", None)
    monkeypatch.setenv("CHAT_HISTORY_STORE", "disabled")
    monkeypatch.setenv("COSMOS_CHAT_ENDPOINT", "https://cosmos.example")
    monkeypatch.setenv("CHAT_ARTIFACT_STORE", "disabled")
    monkeypatch.setenv("CHAT_ARTIFACT_BLOB_ENDPOINT", "https://blob.example")

    # Act & Assert
    with pytest.raises(ChatHistoryError, match="history is disabled"):
        chat_history_store.get_chat_history_repository()
    with pytest.raises(ChatHistoryError, match="artifacts are disabled"):
        chat_history_store.get_artifact_store()


def test_given_missing_store_modes_when_resolved_then_configuration_fails_closed(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setattr(chat_history_store, "_history_repository", None)
    monkeypatch.setattr(chat_history_store, "_artifact_store", None)
    monkeypatch.delenv("CHAT_HISTORY_STORE", raising=False)
    monkeypatch.delenv("CHAT_ARTIFACT_STORE", raising=False)

    # Act & Assert
    with pytest.raises(ChatHistoryError, match="CHAT_HISTORY_STORE must be"):
        chat_history_store.get_chat_history_repository()
    with pytest.raises(ChatHistoryError, match="CHAT_ARTIFACT_STORE must be"):
        chat_history_store.get_artifact_store()