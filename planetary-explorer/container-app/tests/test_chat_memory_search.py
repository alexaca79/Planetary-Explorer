"""Canonical validation and owner-isolation tests for saved-chat recall."""

from __future__ import annotations

import pytest

from chat_history_store import InMemoryChatHistoryRepository, opaque_owner_key
from chat_memory_search import ChatMemorySearch, build_memory_documents, create_memory_index_schema, recall_saved_context


async def _save(repository, owner="tenant:user", session_id="earlier", **overrides):
    return await repository.upsert_session(owner, session_id, {
        "mutationId": "first-save",
        "expectedRevision": 0,
        "messages": [{"role": "user", "content": "Thunder Bay baseline is June 1, 2026."}],
        **overrides,
    })


class StubSearchClient:
    def __init__(self, results=None):
        self.results = results or []
        self.calls = []
        self.uploaded = []
        self.deleted = []

    async def search(self, query, **options):
        self.calls.append((query, options))
        return self.results

    async def upload_documents(self, documents):
        self.uploaded.extend(documents)

    async def delete_documents(self, documents):
        self.deleted.extend(documents)


@pytest.mark.asyncio
async def test_given_saved_chats_when_search_unconfigured_then_recall_uses_owned_history():
    repository = InMemoryChatHistoryRepository()
    await _save(repository)
    await _save(repository, owner="other:user", session_id="private")

    result = await recall_saved_context("tenant:user", "current", "Thunder Bay baseline", repository)

    assert result["provider"] == "history"
    assert [memory["sessionId"] for memory in result["memories"]] == ["earlier"]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["changed", "deleted", "deleting", "excluded", "foreign"])
async def test_given_stale_or_unowned_hit_when_recalled_then_no_content_is_exposed(state):
    repository = InMemoryChatHistoryRepository()
    document = await _save(repository)
    hits = build_memory_documents("tenant:user", document)
    if state == "changed":
        await _save(repository, mutationId="correction", expectedRevision=1, messages=[{"role": "user", "content": "Baseline now July 1."}])
    elif state == "deleted":
        await repository.delete_session("tenant:user", "earlier")
    elif state == "deleting":
        await repository.begin_delete("tenant:user", "earlier", document["_etag"])
    elif state == "excluded":
        await _save(repository, mutationId="exclude", expectedRevision=1, memoryEnabled=False)
    else:
        hits[0]["ownerKey"] = opaque_owner_key("other:user")
    index = ChatMemorySearch(StubSearchClient(hits))

    result = await recall_saved_context("tenant:user", "current", "baseline", repository, index=index)

    assert result["memories"] == []


@pytest.mark.asyncio
async def test_given_search_query_when_recalled_then_owner_filter_is_server_controlled():
    client = StubSearchClient()
    index = ChatMemorySearch(client)

    await index.search("tenant:user", "chat' or true", "baseline *")

    query, options = client.calls[0]
    assert query == "baseline"
    assert options["filter"] == f"ownerKey eq '{opaque_owner_key('tenant:user')}' and sessionId ne 'chat'' or true'"
    assert "content" not in options["select"]


@pytest.mark.asyncio
async def test_given_session_when_indexed_then_keys_are_owner_scoped_and_sensitive_payloads_excluded():
    repository = InMemoryChatHistoryRepository()
    document = await _save(repository, messages=[{"role": "user", "content": "baseline api_key=private-value"}])
    client = StubSearchClient()

    await ChatMemorySearch(client).sync_session("tenant:user", document)

    assert len(client.uploaded) == 1
    assert "private-value" not in str(client.uploaded)
    assert len(client.deleted) == 199
    assert not set(client.uploaded[0]) & {"attachments", "context", "ownerId"}


@pytest.mark.asyncio
async def test_given_memory_setting_when_resaved_by_older_client_then_opt_out_is_preserved():
    repository = InMemoryChatHistoryRepository()
    await _save(repository, memoryEnabled=False)

    document = await _save(repository, mutationId="second-save", expectedRevision=1)

    assert document["memoryEnabled"] is False


def test_given_index_schema_when_created_then_security_fields_are_filterable():
    schema = create_memory_index_schema("chat-memory-test")

    fields = {field.name: field for field in schema.fields}

    assert fields["ownerKey"].filterable
    assert fields["sessionId"].filterable
    assert schema.semantic_search.configurations[0].name == "chat-memory"


@pytest.mark.asyncio
async def test_given_unindexed_history_when_recalling_previous_chat_then_fallback_finds_it():
    repository = InMemoryChatHistoryRepository()
    await _save(repository)
    index = ChatMemorySearch(StubSearchClient())

    result = await recall_saved_context("tenant:user", "current", "What did we discuss in the previous chat?", repository, index=index)

    assert result["provider"] == "history"
    assert result["memories"][0]["sessionId"] == "earlier"


@pytest.mark.asyncio
async def test_given_failing_search_when_recalling_then_history_remains_available():
    repository = InMemoryChatHistoryRepository()
    await _save(repository)

    class FailedSearch(StubSearchClient):
        async def search(self, *args, **kwargs):
            raise ConnectionError("Search offline")

    result = await recall_saved_context("tenant:user", "current", "Thunder Bay baseline", repository, index=ChatMemorySearch(FailedSearch()))

    assert result["provider"] == "history"
    assert result["memories"][0]["sessionId"] == "earlier"