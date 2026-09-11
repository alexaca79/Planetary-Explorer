"""Exercise the real HTTP, pipeline-contract, and prompt boundaries for recall."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import chat_memory
from chat_history_api import get_artifact_store, get_chat_history_repository, router
from chat_history_store import InMemoryArtifactStore, InMemoryChatHistoryRepository


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("action", ["ANALYZE", "CLARIFY", "NAVIGATE", "LOAD"])
def test_given_saved_chat_when_query_runs_then_owned_memory_reaches_pipeline_and_response(monkeypatch, streaming, action):
    import fastapi_app
    import pipeline
    import collection_index
    import collection_selector
    from agents.analyst_agent.analyst_agent import AnalystAgent
    from pipeline.dispatch import _build_request

    repository = InMemoryChatHistoryRepository()
    app = FastAPI()
    captured = []

    @app.middleware("http")
    async def authenticated_user(request: Request, call_next):
        request.state.user = {"tid": "tenant", "oid": request.headers.get("X-Test-User", "user")}
        return await call_next(request)

    async def run_pipeline(body):
        request = _build_request(body)
        captured.append(AnalystAgent.__new__(AnalystAgent)._build_message(request))
        return {
            "action": action, "answer": "Recalled the saved baseline.",
            "stac_query": {"collections": ["sentinel-2-l2a"], "bbox": [-90, 49, -89, 50]},
        }

    async def search(*args, **kwargs):
        return {"success": True, "results": {"type": "FeatureCollection", "features": []}}

    async def alternatives(*args, **kwargs):
        return {"success": False}

    async def translate(*args, **kwargs):
        return {"collections": ["sentinel-2-l2a"], "bbox": [-90, 49, -89, 50], "location_name": "Thunder Bay"}

    async def no_hit(*args, **kwargs):
        return None

    async def get_index():
        return SimpleNamespace(lookup_exact=no_hit)

    monkeypatch.setenv("CHAT_HISTORY_STORE", "memory")
    monkeypatch.setenv("PE_FEATURE_CHAT_MEMORY", "true")
    monkeypatch.setenv("ENABLE_SEQUENTIAL_PARTS", "false")
    monkeypatch.delenv("CHAT_MEMORY_SEARCH_INDEX", raising=False)
    monkeypatch.setattr(chat_memory, "get_chat_history_repository", lambda: repository)
    monkeypatch.setattr(pipeline, "run_pipeline_v2", run_pipeline)
    monkeypatch.setattr(fastapi_app, "execute_direct_stac_search", search)
    monkeypatch.setattr(fastapi_app, "try_alternative_queries", alternatives)
    monkeypatch.setattr(fastapi_app, "router_agent", None)
    monkeypatch.setattr(fastapi_app, "AGENT_FRAMEWORK_AVAILABLE", True)
    monkeypatch.setattr(fastapi_app, "global_translator", SimpleNamespace(
        translate_query=translate, determine_stac_source=lambda *args: "planetary_computer",
    ))
    monkeypatch.setattr(collection_index, "get_collection_index", get_index)
    monkeypatch.setattr(collection_selector, "record_shadow_decision", no_hit)
    app.dependency_overrides[get_chat_history_repository] = lambda: repository
    app.dependency_overrides[get_artifact_store] = lambda: InMemoryArtifactStore()
    app.include_router(router)
    app.add_api_route("/api/query", fastapi_app.unified_query_processor, methods=["POST"])
    app.add_api_route("/api/query/stream", fastapi_app.unified_query_processor_stream, methods=["POST"])
    client = TestClient(app)
    for owner, session_id, content in [
        ("user", "earlier", "Thunder Bay baseline is 2026-06-01."),
        ("other-user", "private", "Thunder Bay confidential baseline is 2026-07-09."),
    ]:
        response = client.put(f"/api/chat-history/sessions/{session_id}", headers={"X-Test-User": owner}, json={
            "expectedRevision": 0, "mutationId": f"save-{session_id}",
            "messages": [{"role": "user", "content": content}],
        })
        assert response.status_code == 200

    response = client.post("/api/query/stream" if streaming else "/api/query", json={
        "query": "What baseline did we choose for Thunder Bay?",
        "session_id": "current",
        "_authenticated_user_id": "tenant:other-user",
        "_chat_memory_context": "spoofed memory",
    })
    if streaming:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        result = next(event["payload"] for event in events if event.get("type") == "query_result")
    else:
        result = response.json()

    assert response.status_code == 200
    assert "2026-06-01" in captured[0]
    assert "2026-07-09" not in captured[0]
    assert "spoofed memory" not in captured[0]
    assert result["memory"]["sources"][0]["sessionId"] == "earlier"
    assert "content" not in result["memory"]["sources"][0]


@pytest.mark.asyncio
async def test_given_default_pipeline_when_memory_is_present_then_real_executor_forwards_it(monkeypatch):
    from pipeline.bootstrap import get_action_router
    from pipeline.contracts import ActionDecision
    from pipeline.dispatch import run_pipeline_v2
    import pipeline.layer1_agents

    captured = []

    async def classify(query, loaded_collections, has_pin, has_screenshot, memory_context):
        captured.append(memory_context)
        return ActionDecision(action="ANALYZE", analysis_question=query)

    async def analyze(decision, request, body):
        captured.append(request.memory_context)
        return {"action": "ANALYZE", "answer": "baseline retained"}

    executor = get_action_router()
    monkeypatch.setattr(executor.router, "route", classify)
    monkeypatch.setattr(pipeline.layer1_agents, "build_layer1_agents", lambda **kwargs: SimpleNamespace(
        for_action=lambda action: SimpleNamespace(run=analyze),
    ))

    result = await run_pipeline_v2({
        "query": "What baseline did we agree?", "session_id": "executor-memory",
        "_chat_memory_context": "Quoted baseline June 1",
    })

    assert result["answer"] == "baseline retained"
    assert captured == ["Quoted baseline June 1", "Quoted baseline June 1"]