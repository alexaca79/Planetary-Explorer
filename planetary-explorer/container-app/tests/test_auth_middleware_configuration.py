"""Authentication middleware configuration tests."""

from __future__ import annotations

import base64
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth_middleware


def _build_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(auth_middleware.EntraAuthMiddleware)

    @app.get("/protected")
    async def protected() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


def _principal_header(*, tenant_id: str | None) -> str:
    claims = [
        {
            "typ": "http://schemas.microsoft.com/identity/claims/objectidentifier",
            "val": "user-id",
        }
    ]
    if tenant_id is not None:
        claims.append({"typ": "tid", "val": tenant_id})
    payload = json.dumps({"claims": claims}).encode("utf-8")
    return base64.b64encode(payload).decode("ascii")


def test_given_missing_entra_ids_when_requesting_protected_path_then_request_fails_closed(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setattr(auth_middleware, "TENANT_ID", "")
    monkeypatch.setattr(auth_middleware, "CLIENT_ID", "")
    monkeypatch.delenv("DISABLE_AUTH", raising=False)
    monkeypatch.delenv("TRUST_EASYAUTH_HEADER", raising=False)

    # Act
    response = _build_client().get("/protected")

    # Assert
    assert response.status_code == 401
    assert response.json() == {"error": "Missing or invalid Authorization header"}


def test_given_entra_ids_when_request_has_no_token_then_secure_mode_rejects_request(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setattr(auth_middleware, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth_middleware, "CLIENT_ID", "client-id")
    monkeypatch.delenv("DISABLE_AUTH", raising=False)
    monkeypatch.delenv("TRUST_EASYAUTH_HEADER", raising=False)

    # Act
    response = _build_client().get("/protected")

    # Assert
    assert response.status_code == 401
    assert response.json() == {"error": "Missing or invalid Authorization header"}


def test_given_explicit_disable_when_entra_ids_exist_then_public_mode_allows_request(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setattr(auth_middleware, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth_middleware, "CLIENT_ID", "client-id")
    monkeypatch.setenv("DISABLE_AUTH", "true")
    monkeypatch.delenv("TRUST_EASYAUTH_HEADER", raising=False)

    # Act
    response = _build_client().get("/protected")

    # Assert
    assert response.status_code == 200


def test_given_untrusted_easyauth_header_when_request_has_no_token_then_request_is_rejected(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setattr(auth_middleware, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth_middleware, "CLIENT_ID", "client-id")
    monkeypatch.delenv("DISABLE_AUTH", raising=False)
    monkeypatch.delenv("TRUST_EASYAUTH_HEADER", raising=False)

    # Act
    response = _build_client().get(
        "/protected",
        headers={"X-MS-CLIENT-PRINCIPAL": _principal_header(tenant_id="tenant-id")},
    )

    # Assert
    assert response.status_code == 401


def test_given_trusted_easyauth_header_with_matching_tenant_then_request_is_allowed(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setattr(auth_middleware, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth_middleware, "CLIENT_ID", "client-id")
    monkeypatch.delenv("DISABLE_AUTH", raising=False)
    monkeypatch.setenv("TRUST_EASYAUTH_HEADER", "true")

    # Act
    response = _build_client().get(
        "/protected",
        headers={"X-MS-CLIENT-PRINCIPAL": _principal_header(tenant_id="tenant-id")},
    )

    # Assert
    assert response.status_code == 200


def test_given_trusted_easyauth_header_without_tenant_then_request_is_rejected(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setattr(auth_middleware, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth_middleware, "CLIENT_ID", "client-id")
    monkeypatch.delenv("DISABLE_AUTH", raising=False)
    monkeypatch.setenv("TRUST_EASYAUTH_HEADER", "true")

    # Act
    response = _build_client().get(
        "/protected",
        headers={"X-MS-CLIENT-PRINCIPAL": _principal_header(tenant_id=None)},
    )

    # Assert
    assert response.status_code == 401