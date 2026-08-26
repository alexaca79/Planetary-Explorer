"""Authentication middleware configuration tests."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest

import auth_middleware


def test_given_secure_wildcard_cors_when_importing_api_then_startup_fails() -> None:
    # Arrange
    environment = os.environ.copy()
    environment["CORS_ORIGINS"] = "*"
    environment["DISABLE_AUTH"] = "false"

    # Act
    result = subprocess.run(
        [sys.executable, "-c", "import fastapi_app"],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    # Assert
    assert result.returncode != 0
    assert "CORS_ORIGINS must list explicit origins" in result.stderr


def test_given_mixed_wildcard_cors_in_public_mode_when_importing_api_then_startup_fails() -> None:
    # Arrange
    environment = os.environ.copy()
    environment["CORS_ORIGINS"] = "*,https://expected.example"
    environment["DISABLE_AUTH"] = "true"

    # Act
    result = subprocess.run(
        [sys.executable, "-c", "import fastapi_app"],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    # Assert
    assert result.returncode != 0
    assert "only configured origin is '*'" in result.stderr


def _build_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(auth_middleware.EntraAuthMiddleware)

    @app.get("/protected")
    async def protected() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


def _principal_header(*, tenant_id: str | None, include_subject: bool = True) -> str:
    claims = []
    if include_subject:
        claims.append(
            {
                "typ": "http://schemas.microsoft.com/identity/claims/objectidentifier",
                "val": "user-id",
            }
        )
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


def test_given_trusted_easyauth_header_without_subject_then_request_is_rejected(
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
        headers={
            "X-MS-CLIENT-PRINCIPAL": _principal_header(
                tenant_id="tenant-id",
                include_subject=False,
            )
        },
    )

    # Assert
    assert response.status_code == 401


@pytest.mark.parametrize(
    "audience",
    [
        "00000003-0000-0000-c000-000000000000",
        "https://graph.microsoft.com",
        "https://graph.microsoft.com/",
    ],
)
def test_given_graph_token_when_requesting_protected_path_then_audience_is_rejected(
    monkeypatch,
    audience: str,
) -> None:
    # Arrange
    tenant_id = "tenant-id"
    client_id = "client-id"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {
            "aud": audience,
            "iss": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            "sub": "user-id",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    monkeypatch.setattr(auth_middleware, "TENANT_ID", tenant_id)
    monkeypatch.setattr(auth_middleware, "CLIENT_ID", client_id)
    monkeypatch.setattr(
        auth_middleware,
        "VALID_ISSUERS",
        [f"https://login.microsoftonline.com/{tenant_id}/v2.0"],
    )
    monkeypatch.setattr(
        auth_middleware,
        "VALID_AUDIENCES",
        [client_id, f"api://{client_id}"],
    )
    monkeypatch.setattr(
        auth_middleware.EntraAuthMiddleware,
        "_signing_key_for_token",
        lambda _self, _token, _issuer: SimpleNamespace(key=private_key.public_key()),
    )
    monkeypatch.delenv("DISABLE_AUTH", raising=False)
    monkeypatch.delenv("TRUST_EASYAUTH_HEADER", raising=False)

    # Act
    response = _build_client().get(
        "/protected",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Assert
    assert response.status_code == 401
    assert response.json() == {"error": "Invalid token audience"}