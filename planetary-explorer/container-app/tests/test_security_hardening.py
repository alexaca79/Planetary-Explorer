"""Security regressions: token error hygiene and hidden operator diagnostics."""

from __future__ import annotations

import base64
import json
import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import auth_middleware

_DIAGNOSTIC_PATHS = {
    "/api/admin/stac-probe",
    "/api/_debug/collection-index",
    "/api/geoint/cmip6-test",
    "/api/debug/location/{location}",
}


def _segment(value: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()


def _forged_token() -> str:
    header = _segment({"alg": "RS256", "kid": "attacker-kid", "typ": "JWT"})
    claims = _segment(
        {
            "iss": "https://evil.example/\nforged-log-line",
            "aud": "client-id",
            "upn": "victim@contoso.example",
        }
    )
    return f"{header}.{claims}.c2lnbmF0dXJl"


def _build_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(auth_middleware.EntraAuthMiddleware)

    @app.get("/protected")
    async def protected() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


def test_given_forged_token_when_rejected_then_response_and_logs_omit_its_claims(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    monkeypatch.setattr(auth_middleware, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth_middleware, "CLIENT_ID", "client-id")
    monkeypatch.delenv("DISABLE_AUTH", raising=False)
    monkeypatch.delenv("TRUST_EASYAUTH_HEADER", raising=False)

    def unknown_key(*_args, **_kwargs):
        raise LookupError("kid attacker-kid not found at https://login.example/keys")

    client = _build_client()
    monkeypatch.setattr(
        auth_middleware.EntraAuthMiddleware, "_signing_key_for_token", unknown_key
    )

    # Act
    with caplog.at_level(logging.WARNING, logger=auth_middleware.__name__):
        response = client.get(
            "/protected", headers={"Authorization": f"Bearer {_forged_token()}"}
        )

    # Assert
    assert response.status_code == 401
    assert response.json() == {"error": "Token validation failed"}
    assert response.headers["www-authenticate"] == "Bearer"
    logged = caplog.text
    assert "LookupError" in logged
    assert "victim@contoso.example" not in logged
    assert "forged-log-line" not in logged
    assert "login.example" not in response.text


def test_given_deployed_api_when_listing_routes_then_every_diagnostic_is_gated_once() -> None:
    # Arrange
    import fastapi_app

    # Act
    diagnostic_routes = [
        route
        for route in fastapi_app.app.routes
        if isinstance(route, APIRoute) and route.path in _DIAGNOSTIC_PATHS
    ]

    # Assert
    assert sorted(route.path for route in diagnostic_routes) == sorted(_DIAGNOSTIC_PATHS)
    for route in diagnostic_routes:
        dependencies = {dependency.call for dependency in route.dependant.dependencies}
        assert fastapi_app._require_diagnostics in dependencies, route.path


def test_given_diagnostics_disabled_when_requested_then_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    import fastapi_app

    monkeypatch.delenv("ENABLE_DIAGNOSTIC_ENDPOINTS", raising=False)

    # Act
    with pytest.raises(HTTPException) as raised:
        fastapi_app._require_diagnostics()

    # Assert
    assert raised.value.status_code == 404


def test_given_diagnostics_enabled_when_requested_then_route_is_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    import fastapi_app

    monkeypatch.setenv("ENABLE_DIAGNOSTIC_ENDPOINTS", "true")

    # Act and assert
    assert fastapi_app._require_diagnostics() is None
