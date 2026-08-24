"""Standard query SSE wrapper tests."""

import json

import pytest
from fastapi.responses import JSONResponse


@pytest.mark.asyncio
async def test_given_confirmation_during_query_when_streaming_then_event_precedes_result(
    monkeypatch,
) -> None:
    # Arrange
    import fastapi_app
    from mcp_runtime import emit_trace

    async def fake_query(_request):
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
        return JSONResponse({"response": "queued", "action": "ANALYZE"})

    monkeypatch.setattr(fastapi_app, "unified_query_processor", fake_query)

    # Act
    response = await fastapi_app.unified_query_processor_stream(object())
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
    assert events[-1]["payload"] == {"response": "queued", "action": "ANALYZE"}