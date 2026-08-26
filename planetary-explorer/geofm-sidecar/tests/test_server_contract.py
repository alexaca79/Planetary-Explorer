"""MCP protocol and tool-surface tests for the GeoFM control plane."""

import hashlib
import hmac
import json
import sys
import time
from types import SimpleNamespace

import anyio
import pytest
from starlette.testclient import TestClient

import geofm_service.server as server_module
from geofm_service.contracts import RunArtifact
from geofm_service.server import (
    _canonical_owner_resource,
    _readiness_response,
    _readiness_snapshot,
    _sign_artifacts,
    _validate_owner_signature,
    build_app,
    geofm_list_models,
    get_service,
    mcp,
)

HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def test_given_geofm_server_when_listing_tools_then_workflow_surface_is_complete() -> None:
    # Act
    tools = anyio.run(mcp.list_tools)

    # Assert
    assert {tool.name for tool in tools} == {
        "geofm_cancel_run",
        "geofm_compare_epochs",
        "geofm_get_run",
        "geofm_list_models",
        "geofm_retry_run",
    }


def test_given_model_registry_when_listed_then_no_worker_import_is_required() -> None:
    # Act
    envelope = anyio.run(geofm_list_models)

    # Assert
    assert envelope.payload["models"][0]["model_id"] == "NRCan/Planaura-1.0"


def test_given_required_jsonrpc_methods_when_called_then_each_returns_http_success(
    monkeypatch,
) -> None:
    # Arrange
    api_key = "test-key-at-least-thirty-two-characters"
    monkeypatch.setenv("GEOFM_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("GEOFM_MCP_API_KEY", api_key)
    monkeypatch.setenv(
        "GEOFM_OWNER_SIGNING_KEY",
        "test-owner-signing-key-at-least-32-characters",
    )
    authenticated_headers = {**HEADERS, "X-API-Key": api_key}
    calls = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "geofm-contract-test", "version": "1.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "prompts/list", "params": {}},
        {"jsonrpc": "2.0", "id": 4, "method": "resources/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "logging/setLevel",
            "params": {"level": "info"},
        },
    ]

    # Act
    with TestClient(build_app()) as client:
        health_status = client.get("/health").status_code
        unauthorized_status = client.post("/mcp", headers=HEADERS, json=calls[0]).status_code
        statuses = [
            client.post("/mcp", headers=authenticated_headers, json=call).status_code
            for call in calls
        ]
        tool_response = client.post(
            "/mcp",
            headers=authenticated_headers,
            json={
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "geofm_list_models", "arguments": {}},
            },
        )

    # Assert
    assert health_status == 200
    assert unauthorized_status == 401
    assert statuses == [200, 200, 200, 200, 200, 200]
    structured = tool_response.json()["result"]["structuredContent"]
    assert structured["payload"]["models"][0]["model_id"] == "NRCan/Planaura-1.0"


def test_given_required_auth_without_key_when_building_app_then_startup_fails(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setenv("GEOFM_REQUIRE_API_KEY", "true")
    monkeypatch.delenv("GEOFM_MCP_API_KEY", raising=False)

    # Act & Assert
    with pytest.raises(RuntimeError, match="GEOFM_MCP_API_KEY is required"):
        build_app()


def test_given_required_auth_without_owner_key_when_building_app_then_startup_fails(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setenv("GEOFM_REQUIRE_API_KEY", "true")
    monkeypatch.setenv(
        "GEOFM_MCP_API_KEY",
        "test-key-at-least-thirty-two-characters",
    )
    monkeypatch.delenv("GEOFM_OWNER_SIGNING_KEY", raising=False)

    # Act & Assert
    with pytest.raises(RuntimeError, match="GEOFM_OWNER_SIGNING_KEY is required"):
        build_app()


def test_given_equal_transport_and_owner_keys_when_building_app_then_startup_fails(
    monkeypatch,
) -> None:
    # Arrange
    shared_key = "same-key-at-least-thirty-two-characters"
    monkeypatch.setenv("GEOFM_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("GEOFM_MCP_API_KEY", shared_key)
    monkeypatch.setenv("GEOFM_OWNER_SIGNING_KEY", shared_key)

    # Act & Assert
    with pytest.raises(RuntimeError, match="must be distinct"):
        build_app()


def test_given_missing_owner_signing_when_checking_health_then_service_is_degraded(
) -> None:
    # Act
    response = _readiness_response(
        {"ready": False, "checks": {"owner_signing": False}}
    )

    # Assert
    assert response.status_code == 503
    assert json.loads(response.body)["checks"]["owner_signing"] is False


def test_given_available_storage_dependencies_when_checking_readiness_then_all_are_verified(
    monkeypatch,
) -> None:
    # Arrange
    class FakeCredential:
        def close(self) -> None:
            pass

    class FakeContainer:
        def __init__(self, **_kwargs) -> None:
            pass

        def exists(self) -> bool:
            return True

        def close(self) -> None:
            pass

    class FakeQueue:
        def __init__(self, *, queue_name, **_kwargs) -> None:
            self.queue_name = queue_name

        def get_queue_properties(self) -> None:
            assert self.queue_name in {"geofm-jobs", "geofm-poison"}

        def close(self) -> None:
            pass

    class FakeBlobService:
        def __init__(self, **_kwargs) -> None:
            pass

        def get_user_delegation_key(self, _start, _expiry):
            return object()

        def close(self) -> None:
            pass

    monkeypatch.setenv(
        "AZURE_STORAGE_BLOB_ENDPOINT",
        "https://storage.blob.core.windows.net",
    )
    monkeypatch.setenv(
        "AZURE_STORAGE_QUEUE_ENDPOINT",
        "https://storage.queue.core.windows.net",
    )
    monkeypatch.setattr(server_module, "DefaultAzureCredential", FakeCredential)
    monkeypatch.setattr(server_module, "ContainerClient", FakeContainer)
    monkeypatch.setitem(
        sys.modules,
        "azure.storage.queue",
        SimpleNamespace(QueueClient=FakeQueue),
    )
    monkeypatch.setattr(server_module, "BlobServiceClient", FakeBlobService)

    # Act
    snapshot = _readiness_snapshot("owner-key-at-least-thirty-two-characters")

    # Assert
    assert snapshot == {
        "ready": True,
        "checks": {
            "owner_signing": True,
            "blob_container": True,
            "work_queue": True,
            "poison_queue": True,
            "blob_delegation": True,
        },
    }


def test_given_equivalent_numeric_and_uuid_values_when_canonicalized_then_proof_matches() -> None:
    # Arrange
    raw = {
        "run_id": "00000000-0000-0000-0000-00000000000A",
        "threshold": 1,
        "geometry": {"coordinates": [[1, 2.5]]},
    }
    normalized = {
        "run_id": "00000000-0000-0000-0000-00000000000a",
        "threshold": 1.0,
        "geometry": {"coordinates": [[1.0, 2.5]]},
    }

    # Act & Assert
    assert _canonical_owner_resource(raw) == _canonical_owner_resource(normalized)


def test_given_operation_bound_owner_signature_when_validating_then_forgery_is_rejected(
    monkeypatch,
) -> None:
    # Arrange
    key = "test-owner-signing-key-at-least-32-characters"
    owner = "tenant:user-1"
    run_id = "00000000-0000-0000-0000-000000000001"
    resource = {"run_id": run_id}
    expires_at = int(time.time()) + 60
    nonce = "0123456789abcdef0123456789abcdef"
    monkeypatch.setenv("GEOFM_OWNER_SIGNING_KEY", key)
    payload = json.dumps(
        ["get", owner, resource, expires_at, nonce],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = hmac.new(key.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    # Act & Assert
    _validate_owner_signature(
        "get",
        owner,
        resource,
        expires_at,
        nonce,
        signature,
    )
    with pytest.raises(PermissionError, match="invalid"):
        _validate_owner_signature(
            "get",
            owner,
            {"run_id": "00000000-0000-0000-0000-000000000002"},
            expires_at,
            nonce,
            signature,
        )
    with pytest.raises(PermissionError, match="expired"):
        _validate_owner_signature(
            "get",
            owner,
            resource,
            int(time.time()) - 1,
            nonce,
            signature,
        )


def test_given_private_artifact_when_polling_then_short_lived_read_url_is_returned(
    monkeypatch,
) -> None:
    # Arrange
    class FakeCredential:
        def close(self) -> None:
            pass

    class FakeBlobService:
        def __init__(self, **_kwargs) -> None:
            pass

        def get_user_delegation_key(self, _start, _expiry):
            return object()

        def close(self) -> None:
            pass

    monkeypatch.setenv(
        "AZURE_STORAGE_BLOB_ENDPOINT",
        "https://storage.blob.core.windows.net",
    )
    monkeypatch.setenv("GEOFM_CONTAINER_NAME", "geofm")
    monkeypatch.setattr(server_module, "DefaultAzureCredential", FakeCredential)
    monkeypatch.setattr(server_module, "BlobServiceClient", FakeBlobService)
    monkeypatch.setattr(server_module, "generate_blob_sas", lambda **_kwargs: "sig=read")
    artifact = RunArtifact(
        kind="evidence_manifest",
        uri="https://storage.blob.core.windows.net/geofm/runs/run-1/evidence.json",
        sha256="a" * 64,
    )

    # Act
    signed = _sign_artifacts([artifact])

    # Assert
    assert signed[0].uri.endswith("?sig=read")
    assert signed[0].sha256 == artifact.sha256


@pytest.mark.parametrize(
    ("blob_endpoint", "queue_endpoint"),
    [
        ("https://storage.blob.core.windows.net", ""),
        ("", "https://storage.queue.core.windows.net"),
    ],
)
def test_given_partial_azure_storage_when_building_service_then_startup_fails(
    monkeypatch,
    blob_endpoint: str,
    queue_endpoint: str,
) -> None:
    # Arrange
    monkeypatch.setenv("AZURE_STORAGE_BLOB_ENDPOINT", blob_endpoint)
    monkeypatch.setenv("AZURE_STORAGE_QUEUE_ENDPOINT", queue_endpoint)
    get_service.cache_clear()

    # Act & Assert
    with pytest.raises(RuntimeError, match="must be configured together"):
        get_service()

    get_service.cache_clear()