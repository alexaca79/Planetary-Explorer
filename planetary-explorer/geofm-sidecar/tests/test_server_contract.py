"""MCP protocol and tool-surface tests for the GeoFM control plane."""

import anyio
import pytest
from starlette.testclient import TestClient

from geofm_service.server import build_app, geofm_list_models, get_service, mcp

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