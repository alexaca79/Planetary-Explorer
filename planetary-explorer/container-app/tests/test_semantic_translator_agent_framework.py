"""Tests for Agent Framework initialization in the query translator."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from _framework.agent_runtime import AgentFrameworkRuntime
from semantic_translator import (
    SemanticQueryTranslator,
    _qualify_location_for_geocoding,
)


def _translator_stub(*, api_key: str | None, credential: Any = None) -> SemanticQueryTranslator:
    translator = object.__new__(SemanticQueryTranslator)
    translator.azure_openai_endpoint = "https://example.openai.azure.com"
    translator.azure_openai_api_key = api_key
    translator.azure_credential = credential
    translator.model_name = "gpt-5"
    translator._model_override = None
    translator.agent_runtime = None
    translator._agent_runtime_initialized = False
    return translator


class _RuntimeStub:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def run(self, prompt: str, **kwargs: Any) -> str:
        self.calls.append({"prompt": prompt, **kwargs})
        return self.response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("api_key", "credential"),
    [
        ("test-key", None),
        (None, object()),
    ],
)
async def test_given_auth_mode_when_initializing_then_runtime_receives_configuration(
    monkeypatch: pytest.MonkeyPatch,
    api_key: str | None,
    credential: Any,
) -> None:
    # Arrange
    translator = _translator_stub(api_key=api_key, credential=credential)
    runtime = object()
    captured: dict[str, Any] = {}

    def create_runtime(**kwargs: Any) -> object:
        captured.update(kwargs)
        return runtime

    monkeypatch.setattr(
        AgentFrameworkRuntime,
        "from_azure_openai",
        staticmethod(create_runtime),
    )
    monkeypatch.setenv("AZURE_OPENAI_FAST_DEPLOYMENT", "gpt-4o-mini-test")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-10-21-test")

    # Act
    available = await translator.initialize_agent_runtime()

    # Assert
    assert captured == {
        "endpoint": "https://example.openai.azure.com",
        "primary_model": "gpt-5",
        "fast_model": "gpt-4o-mini-test",
        "api_key": api_key,
        "credential": credential,
        "api_version": "2024-10-21-test",
    }
    assert translator.agent_runtime is runtime
    assert translator._agent_runtime_initialized is True
    assert available is True


@pytest.mark.asyncio
async def test_given_factory_failure_when_initializing_then_runtime_remains_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    translator = _translator_stub(api_key="test-key")

    def fail_runtime(**_kwargs: Any) -> object:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        AgentFrameworkRuntime,
        "from_azure_openai",
        staticmethod(fail_runtime),
    )

    # Act
    available = await translator.initialize_agent_runtime()

    # Assert
    assert translator.agent_runtime is None
    assert translator._agent_runtime_initialized is False
    assert available is False


@pytest.mark.asyncio
async def test_given_basic_fallback_when_query_has_city_and_dates_then_both_are_preserved() -> None:
    translator = _translator_stub(api_key="test-key")
    translator._extract_location_basic = AsyncMock(return_value="canada")
    translator.resolve_location_to_bbox = AsyncMock(
        return_value=[-104.62402, 50.39419, -104.62215, 50.39601]
    )
    translator._validate_bbox = lambda bbox: len(bbox) == 4

    result = await translator._build_stac_query_basic(
        "Show HLS L30 imagery over Regina, Saskatchewan, Canada "
        "from 2026-07-17 to 2026-08-18",
        ["hls2-l30"],
    )

    assert result["datetime"] == "2026-07-17/2026-08-18"
    assert result["location_name"] == "Regina, Saskatchewan, Canada"
    assert result["bbox"] == [-104.62402, 50.39419, -104.62215, 50.39601]
    translator.resolve_location_to_bbox.assert_awaited_once_with(
        "Regina, Saskatchewan, Canada",
        "region",
    )


@pytest.mark.asyncio
async def test_given_valid_location_json_when_resolving_then_bbox_comes_from_agent_runtime() -> None:
    # Arrange
    translator = _translator_stub(api_key="test-key")
    runtime = _RuntimeStub(
        '{"bbox": [-122.45, 47.48, -122.22, 47.74], "confidence": 0.95}'
    )
    translator.agent_runtime = runtime
    translator._agent_runtime_initialized = True

    # Act
    result = await translator._resolve_via_agent_framework("Seattle", "city")

    # Assert
    assert result == [-122.45, 47.48, -122.22, 47.74]
    assert runtime.calls[0]["response_format"] == {"type": "json_object"}


def test_given_new_model_when_set_model_then_runtime_is_reset() -> None:
    # Arrange
    translator = _translator_stub(api_key="test-key")
    translator.agent_runtime = object()
    translator._agent_runtime_initialized = True

    # Act
    translator.set_model("gpt-4o")

    # Assert
    assert translator.get_active_model() == "gpt-4o"
    assert translator.agent_runtime is None
    assert translator._agent_runtime_initialized is False


def test_given_canadian_query_when_entity_omits_country_then_qualifier_is_restored() -> None:
    assert _qualify_location_for_geocoding(
        "Show HLS imagery over Regina, Canada",
        "Regina",
    ) == "Regina, Canada"


def test_given_coarse_country_entity_when_query_names_city_then_city_is_restored() -> None:
    assert _qualify_location_for_geocoding(
        "Show HLS imagery over Regina, Saskatchewan, Canada from 2026-07-17",
        "Canada",
    ) == "Regina, Saskatchewan, Canada"