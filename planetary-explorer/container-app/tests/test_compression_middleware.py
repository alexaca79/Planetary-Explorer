"""Response compression contracts for JSON, streams, and binary tiles."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import Response, StreamingResponse
from fastapi.testclient import TestClient

from security_middleware import CompressionMiddleware, SecurityHeadersMiddleware

_FEATURES = {"features": [{"id": f"S2A_MSIL2A_{index}", "bbox": [-79.5, 43.6, -79.3, 43.8]} for index in range(200)]}


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/api/stac")
    async def stac() -> dict:
        return _FEATURES

    @app.get("/api/query/stream")
    async def stream() -> StreamingResponse:
        async def events():
            for index in range(50):
                yield f"data: {{\"step\": {index}, \"padding\": \"{'x' * 64}\"}}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/api/pro/tile/{rest:path}")
    async def tile(rest: str) -> Response:
        return Response(content=b"\x89PNG" + b"\x00" * 4096, media_type="image/png")

    app.add_middleware(CompressionMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    return TestClient(app)


def test_given_large_json_when_client_accepts_gzip_then_response_is_compressed() -> None:
    # Act
    response = _client().get("/api/stac", headers={"Accept-Encoding": "gzip"})

    # Assert
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json() == _FEATURES


def test_given_event_stream_when_client_accepts_gzip_then_events_are_not_buffered() -> None:
    # Act
    response = _client().get("/api/query/stream", headers={"Accept-Encoding": "gzip"})

    # Assert
    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.text.count("data: ") == 50


def test_given_tile_proxy_when_client_accepts_gzip_then_image_bytes_pass_through() -> None:
    # Act
    response = _client().get("/api/pro/tile/10/300/370.png", headers={"Accept-Encoding": "gzip"})

    # Assert
    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.content.startswith(b"\x89PNG")
