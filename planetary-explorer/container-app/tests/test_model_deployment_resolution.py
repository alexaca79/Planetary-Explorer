"""Configured model deployment routing tests."""

import json

import pytest


def test_given_unavailable_requested_model_when_resolving_then_configured_model_wins(
    monkeypatch,
) -> None:
    # Arrange
    import fastapi_app

    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")

    # Act
    resolved = fastapi_app._resolve_chat_deployment("gpt-5")

    # Assert
    assert resolved == "gpt-4o"


def test_given_no_requested_model_when_resolving_then_configured_model_is_used(
    monkeypatch,
) -> None:
    # Arrange
    import fastapi_app

    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")

    # Act and assert
    assert fastapi_app._resolve_chat_deployment(None) == "gpt-4o"


@pytest.mark.asyncio
async def test_given_configured_model_when_health_requested_then_model_is_advertised(
    monkeypatch,
) -> None:
    # Arrange
    import fastapi_app

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class FakeSession:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def get(self, _url):
            return FakeResponse()

    async def fake_geofm_health():
        return {
            "enabled": False,
            "connected": False,
            "status": "disabled",
            "tool_count": 0,
            "tools": [],
            "models": [],
        }

    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")
    monkeypatch.setenv("USE_MANAGED_IDENTITY", "true")
    monkeypatch.setenv("AZURE_MAPS_KEY", "configured")
    monkeypatch.setattr(fastapi_app.aiohttp, "ClientSession", FakeSession)
    monkeypatch.setattr(fastapi_app, "get_health_snapshot", fake_geofm_health)

    # Act
    response = await fastapi_app.health_check()
    payload = json.loads(response.body)

    # Assert
    assert response.status_code == 200
    assert payload["checks"]["azure_openai"]["model"] == "gpt-4o"
    assert payload["checks"]["azure_openai"]["available_models"] == ["gpt-4o"]