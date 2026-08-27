"""Standard query SSE wrapper tests."""

import json

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


class _BodyCachingRequest:
    """Require body caching before JSON can be read by the stream iterator."""

    def __init__(self) -> None:
        self.body_cached = False

    async def body(self) -> bytes:
        self.body_cached = True
        return b'{"query":"show fires"}'

    async def json(self) -> dict[str, str]:
        assert self.body_cached
        return {"query": "show fires"}


@pytest.mark.asyncio
async def test_given_confirmation_during_query_when_streaming_then_event_precedes_result(
    monkeypatch,
) -> None:
    # Arrange
    import fastapi_app
    from mcp_runtime import emit_trace

    async def fake_query(request):
        request_body = await request.json()
        await emit_trace(
            {
                "type": "confirm_request",
                "trace_id": "trace-geofm",
                "server_id": "geofm",
                "tool": "geofm_compare_epochs",
                "tier": "write",
                "args": {},
            }
        )
        return JSONResponse(
            {
                "response": "queued",
                "action": "ANALYZE",
                "query": request_body["query"],
            }
        )

    monkeypatch.setattr(fastapi_app, "unified_query_processor", fake_query)

    # Act
    response = await fastapi_app.unified_query_processor_stream(_BodyCachingRequest())
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    events = [
        json.loads(block.split("data: ", 1)[1])
        for block in "".join(chunks).split("\n\n")
        if block.startswith("data: ")
    ]

    # Assert
    assert [event["type"] for event in events] == ["confirm_request", "query_result"]
    assert events[-1]["payload"] == {
        "response": "queued",
        "action": "ANALYZE",
        "query": "show fires",
    }


def test_given_real_asgi_request_when_streaming_then_body_remains_available(
    monkeypatch,
) -> None:
    # Arrange
    import fastapi_app

    async def fake_query(request):
        request_body = await request.json()
        return JSONResponse({"response": request_body["query"]})

    monkeypatch.setattr(fastapi_app, "unified_query_processor", fake_query)
    app = FastAPI()
    app.add_api_route(
        "/api/query/stream",
        fastapi_app.unified_query_processor_stream,
        methods=["POST"],
    )

    # Act
    response = TestClient(app).post(
        "/api/query/stream",
        json={"query": "show fires"},
    )

    # Assert
    assert response.status_code == 200
    assert '"type": "query_result"' in response.text
    assert '"response": "show fires"' in response.text