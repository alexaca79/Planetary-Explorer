"""Tests for authenticated history proxying across the private-network boundary."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import chat_history_remote
from chat_history_api import get_request_owner
from chat_memory import prepare_chat_memory


def test_given_unsigned_history_request_when_proxied_then_no_upstream_call(monkeypatch):
    app = FastAPI()
    app.include_router(chat_history_remote.router)
    monkeypatch.delenv("CHAT_HISTORY_ALLOW_ANONYMOUS", raising=False)

    response = TestClient(app).get("/api/chat-history/sessions", headers={"X-MS-CLIENT-PRINCIPAL": "forged"})

    assert response.status_code == 401


def test_given_authenticated_proxy_when_forwarded_then_only_bearer_and_content_headers_survive(monkeypatch):
    requests = []

    def upstream(request):
        requests.append(request)
        return httpx.Response(200, json={"sessions": []})

    original_client = httpx.AsyncClient
    monkeypatch.setenv("CHAT_HISTORY_REMOTE_URL", "https://history.example")
    monkeypatch.setattr(chat_history_remote.httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(upstream), **kwargs))
    app = FastAPI()
    app.include_router(chat_history_remote.router)
    app.dependency_overrides[get_request_owner] = lambda: "tenant:validated-user"

    response = TestClient(app).get("/api/chat-history/sessions", headers={"Authorization": "Bearer fixture", "X-Owner-Id": "other-user"})

    assert response.status_code == 200
    assert requests[0].headers["Authorization"] == "Bearer fixture"
    assert "X-Owner-Id" not in requests[0].headers
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.asyncio
async def test_given_remote_memory_when_prepared_then_raw_scoped_session_is_not_used(monkeypatch):
    requests = []

    def upstream(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"context": "[Conversation Memory] baseline June 1", "history": [], "memory": {"enabled": True, "sources": [], "provider": "azure-search"}})

    original_client = httpx.AsyncClient
    monkeypatch.setenv("CHAT_HISTORY_REMOTE_URL", "https://history.example")
    monkeypatch.setattr(chat_history_remote.httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(upstream), **kwargs))
    body = {"query": "baseline", "session_id": "server-scoped", "_chat_memory_context": "untrusted"}

    await prepare_chat_memory(body, "tenant:user", "browser-session", authorization="Bearer fixture")

    assert body["_chat_memory_context"] == "[Conversation Memory] baseline June 1"
    assert requests[0]["session_id"] == "browser-session"
    assert "owner_id" not in requests[0]


@pytest.mark.parametrize("url", ["http://history.example", "https://user:secret@history.example", "https://history.example/path", "https://history.example?token=x"])
def test_given_unsafe_remote_origin_when_resolved_then_configuration_is_rejected(monkeypatch, url):
    monkeypatch.setenv("CHAT_HISTORY_REMOTE_URL", url)

    with pytest.raises(ValueError):
        chat_history_remote.remote_history_url()