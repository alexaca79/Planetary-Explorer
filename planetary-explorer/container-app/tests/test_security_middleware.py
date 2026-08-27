"""Tests for the FastAPI HTTP security boundary."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

import auth_middleware
from security_middleware import (
    HealthProbeTrustedHostMiddleware,
    RequestBodyLimitMiddleware,
    SecurityHeadersMiddleware,
)


def _security_client(*, max_body_bytes: int = 32) -> TestClient:
    app = FastAPI()

    @app.get("/api/status")
    async def status() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"bytes": len(await request.body())}

    app.add_middleware(RequestBodyLimitMiddleware, max_body_bytes=max_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware)
    return TestClient(app)


def test_given_oversized_body_when_posting_then_request_is_rejected() -> None:
    # Arrange
    client = _security_client(max_body_bytes=8)

    # Act
    response = client.post("/api/echo", content=b"123456789")

    # Assert
    assert response.status_code == 413
    assert response.json() == {"error": "Request body too large"}


def test_given_https_request_when_responding_then_security_headers_are_present() -> None:
    # Arrange
    client = _security_client()

    # Act
    response = client.get("/api/status", headers={"X-Forwarded-Proto": "https"})

    # Assert
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["strict-transport-security"].startswith("max-age=31536000")
    assert len(response.headers["x-request-id"]) == 32


def test_given_cors_preflight_when_security_wraps_cors_then_both_header_sets_are_present() -> None:
    # Arrange
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://canada.example"],
        allow_methods=["POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    client = TestClient(app)

    # Act
    response = client.options(
        "/api/query",
        headers={
            "Origin": "https://canada.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )

    # Assert
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://canada.example"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_given_internal_host_when_requesting_health_then_only_health_bypasses_host_check() -> None:
    # Arrange
    app = FastAPI()

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/status")
    async def status() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(
        HealthProbeTrustedHostMiddleware,
        allowed_hosts=["*.azurecontainerapps.io"],
    )
    client = TestClient(app)

    # Act
    health_response = client.get("/api/health", headers={"Host": "100.100.0.103"})
    status_response = client.get("/api/status", headers={"Host": "100.100.0.103"})

    # Assert
    assert health_response.status_code == 200
    assert status_response.status_code == 400


def test_given_pro_collection_inventory_when_checking_open_paths_then_auth_is_required() -> None:
    # Act
    is_open = auth_middleware._is_open_path("/api/pro/collections")

    # Assert
    assert is_open is False


def test_given_dev_bypass_with_auth_enabled_when_stack_builds_then_configuration_fails(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setenv("RESILIENCE_DEV_BYPASS_AUTH", "true")
    monkeypatch.delenv("DISABLE_AUTH", raising=False)
    app = FastAPI()
    app.add_middleware(auth_middleware.EntraAuthMiddleware)

    # Act & Assert
    try:
        with TestClient(app) as client:
            client.get("/protected")
    except RuntimeError as exc:
        assert "requires DISABLE_AUTH=true" in str(exc)
    else:
        raise AssertionError("Insecure development bypass configuration was accepted")