"""Health probe contracts: cheap probes and cached dependency checks."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth_middleware
from security_middleware import HealthProbeTrustedHostMiddleware


class _CountingSession:
    created = 0

    def __init__(self, **_kwargs):
        type(self).created += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def get(self, _url):
        return _OkResponse()


class _OkResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


def _configure_health(monkeypatch: pytest.MonkeyPatch, geofm_calls: list[int]):
    import fastapi_app

    async def fake_geofm_health():
        geofm_calls.append(1)
        return {"enabled": False, "connected": False, "status": "disabled"}

    _CountingSession.created = 0
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("USE_MANAGED_IDENTITY", "true")
    monkeypatch.setenv("AZURE_MAPS_KEY", "configured")
    monkeypatch.setattr(fastapi_app.aiohttp, "ClientSession", _CountingSession)
    monkeypatch.setattr(fastapi_app, "get_health_snapshot", fake_geofm_health)
    return fastapi_app


@pytest.mark.asyncio
async def test_given_repeated_health_requests_when_cache_is_warm_then_dependencies_probe_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    geofm_calls: list[int] = []
    api = _configure_health(monkeypatch, geofm_calls)
    monkeypatch.setenv("HEALTH_DEPENDENCY_CACHE_SECONDS", "30")

    # Act
    first = await api.health_check()
    second = await api.health_check()

    # Assert
    assert first.status_code == second.status_code == 200
    assert json.loads(second.body)["checks"]["stac_api"] == {"status": "connected"}
    assert _CountingSession.created == 1
    assert geofm_calls == [1]


@pytest.mark.asyncio
async def test_given_zero_cache_seconds_when_health_requested_then_each_call_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    geofm_calls: list[int] = []
    api = _configure_health(monkeypatch, geofm_calls)
    monkeypatch.setenv("HEALTH_DEPENDENCY_CACHE_SECONDS", "0")

    # Act
    await api.health_check()
    await api.health_check()

    # Assert
    assert _CountingSession.created == 2
    assert geofm_calls == [1, 1]


@pytest.mark.asyncio
async def test_given_unreachable_dependencies_when_probing_liveness_then_no_external_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    import fastapi_app

    def fail_session(**_kwargs):
        raise AssertionError("probes must not call external services")

    async def fail_geofm():
        raise AssertionError("probes must not call GeoFM")

    monkeypatch.setattr(fastapi_app.aiohttp, "ClientSession", fail_session)
    monkeypatch.setattr(fastapi_app, "get_health_snapshot", fail_geofm)

    # Act
    live = await fastapi_app.health_live()
    ready = await fastapi_app.health_ready()

    # Assert
    assert live == {"status": "alive"}
    assert ready == {"status": "ready"}


@pytest.mark.parametrize(
    ("path", "is_open"),
    [
        ("/api/health/live", True),
        ("/api/health/ready", True),
        ("/api/health/liveness-admin", False),
        ("/api/health/ready/extra", False),
    ],
)
def test_given_probe_paths_when_checking_auth_then_only_exact_paths_are_open(
    path: str,
    is_open: bool,
) -> None:
    # Act and assert
    assert auth_middleware._is_open_path(path) is is_open


def test_given_pod_ip_host_when_probing_then_only_probe_paths_bypass_host_check() -> None:
    # Arrange
    app = FastAPI()

    @app.get("/api/health/live")
    async def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/api/query")
    async def query() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(HealthProbeTrustedHostMiddleware, allowed_hosts=["example.org"])
    client = TestClient(app)

    # Act
    probe = client.get("/api/health/live", headers={"Host": "100.100.0.133"})
    query_response = client.get("/api/query", headers={"Host": "100.100.0.133"})

    # Assert
    assert probe.status_code == 200
    assert query_response.status_code == 400
