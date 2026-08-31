"""Regression tests for stable public errors on agent-backed endpoints."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import fastapi_app
from agents import forecast as forecast_module
from agents import site_intel as site_intel_module


class _JsonRequest:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.state = SimpleNamespace(user={})

    async def json(self) -> dict:
        return self._payload


@pytest.mark.asyncio
async def test_given_site_provider_secret_when_audit_fails_then_client_gets_stable_error(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setattr(fastapi_app, "_require_fabric_assertion", lambda _request: "token")
    monkeypatch.setattr(site_intel_module, "is_available", lambda: True)

    async def fail_site_audit(**_kwargs):
        raise RuntimeError("https://private.example?sig=site-secret")

    monkeypatch.setattr(site_intel_module, "audit_site_v2", fail_site_audit)

    # Act & Assert
    with pytest.raises(HTTPException) as error:
        await fastapi_app.sites_audit(_JsonRequest({"lat": 43.65, "lng": -79.38}))
    assert error.value.status_code == 502
    assert error.value.detail == "Site Intel analysis failed."


@pytest.mark.asyncio
async def test_given_forecast_provider_secret_when_execution_fails_then_client_gets_stable_error(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setenv("FORECAST_AGENT_ENABLED", "true")
    monkeypatch.setattr(forecast_module, "is_available", lambda: True)

    async def fail_forecast(_query):
        raise RuntimeError("provider credential=forecast-secret")

    monkeypatch.setattr(forecast_module, "forecast", fail_forecast)

    # Act & Assert
    with pytest.raises(HTTPException) as error:
        await fastapi_app.geoint_forecast(
            _JsonRequest({"latitude": 43.65, "longitude": -79.38})
        )
    assert error.value.status_code == 503
    assert error.value.detail == "Forecast providers are temporarily unavailable."