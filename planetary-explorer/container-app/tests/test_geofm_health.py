"""GeoFM health snapshot tests."""

from __future__ import annotations

import asyncio

import pytest

import connectors.geofm as geofm_module


class _FakeClient:
    available_tools = (
        "geofm_compare_epochs",
        "geofm_get_run",
        "geofm_list_models",
    )
    closed = False

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def call_raw(self, _tool: str, _arguments: dict) -> dict:
        return {
            "payload": {
                "models": [
                    {
                        "profile": "planaura_hls",
                        "model_id": "NRCan/Planaura-1.0",
                        "model_revision": "revision-1",
                        "approval_state": "conditional",
                        "supported_collections": ["hls2-s30"],
                        "geographic_scope": "Canada",
                        "license": "OGL-Canada-2.0",
                    }
                ]
            }
        }

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_given_connected_geofm_when_probed_then_models_and_tools_are_reported(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setenv("GEOFM_ENABLED", "true")
    monkeypatch.setenv("GEOFM_MCP_URL", "https://geofm.example")
    monkeypatch.setattr(geofm_module, "RemoteMcpClient", _FakeClient)
    geofm_module.get_health_client.cache_clear()

    # Act
    snapshot = await geofm_module.get_health_snapshot()

    # Assert
    assert snapshot == {
        "enabled": True,
        "connected": True,
        "endpoint_host": "geofm.example",
        "status": "connected",
        "tool_count": 3,
        "tools": [
            "geofm_compare_epochs",
            "geofm_get_run",
            "geofm_list_models",
        ],
        "models": [
            {
                "profile": "planaura_hls",
                "model_id": "NRCan/Planaura-1.0",
                "model_revision": "revision-1",
                "approval_state": "conditional",
                "supported_collections": ["hls2-s30"],
                "geographic_scope": "Canada",
                "license": "OGL-Canada-2.0",
            }
        ],
    }
    geofm_module.get_health_client.cache_clear()


@pytest.mark.asyncio
async def test_given_disabled_geofm_when_probed_then_optional_service_is_reported_disabled(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setenv("GEOFM_ENABLED", "false")
    monkeypatch.delenv("GEOFM_MCP_URL", raising=False)

    # Act
    snapshot = await geofm_module.get_health_snapshot()

    # Assert
    assert snapshot["status"] == "disabled"
    assert snapshot["enabled"] is False
    assert snapshot["connected"] is False


@pytest.mark.asyncio
async def test_given_repeated_health_probes_then_one_client_instance_is_reused(
    monkeypatch,
) -> None:
    # Arrange
    created = 0

    class CountingClient(_FakeClient):
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal created
            created += 1

    monkeypatch.setenv("GEOFM_ENABLED", "true")
    monkeypatch.setenv("GEOFM_MCP_URL", "https://geofm.example")
    monkeypatch.setattr(geofm_module, "RemoteMcpClient", CountingClient)
    geofm_module.get_health_client.cache_clear()

    # Act
    await geofm_module.get_health_snapshot()
    await geofm_module.get_health_snapshot()

    # Assert
    assert created == 1
    geofm_module.get_health_client.cache_clear()


@pytest.mark.asyncio
async def test_given_concurrent_health_probes_then_callers_share_one_snapshot(
    monkeypatch,
) -> None:
    # Arrange
    release = asyncio.Event()
    calls = 0

    class BlockingClient(_FakeClient):
        async def call_raw(self, tool: str, arguments: dict) -> dict:
            nonlocal calls
            calls += 1
            await release.wait()
            return await super().call_raw(tool, arguments)

    monkeypatch.setenv("GEOFM_ENABLED", "true")
    monkeypatch.setenv("GEOFM_MCP_URL", "https://geofm.example")
    monkeypatch.setattr(geofm_module, "RemoteMcpClient", BlockingClient)
    geofm_module.get_health_client.cache_clear()
    geofm_module._health_probe_task = None

    # Act
    probes = [asyncio.create_task(geofm_module.get_health_snapshot()) for _ in range(3)]
    await asyncio.sleep(0)
    release.set()
    snapshots = await asyncio.gather(*probes)

    # Assert
    assert calls == 1
    assert [snapshot["status"] for snapshot in snapshots] == [
        "connected",
        "connected",
        "connected",
    ]
    geofm_module.get_health_client.cache_clear()
    geofm_module._health_probe_task = None
