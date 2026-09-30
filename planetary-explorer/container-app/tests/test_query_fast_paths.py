"""Deterministic fast paths that avoid model calls for explicit query details."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from semantic_translator import SemanticQueryTranslator, _explicit_iso_range


def _translator(runtime=None) -> SemanticQueryTranslator:
    translator = object.__new__(SemanticQueryTranslator)
    translator._agent_runtime_initialized = True
    translator.agent_runtime = runtime
    return translator


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Show Sentinel-2 imagery over Toronto, Canada from 2026-06-01 to 2026-08-26", "2026-06-01/2026-08-26"),
        ("Landsat between 2025-01-01 and 2025-02-01", "2025-01-01/2025-02-01"),
        ("Show imagery from 2025-08-31 to 2025-07-01", None),
        ("Show imagery from 2025-02-30 to 2025-03-01", None),
        ("Show imagery closest to 2026-08-28", None),
        ("Show imagery from June 2025", None),
    ],
)
def test_given_query_when_reading_iso_range_then_only_explicit_ranges_are_returned(query, expected) -> None:
    assert _explicit_iso_range(query) == expected


@pytest.mark.asyncio
async def test_given_explicit_iso_range_when_translating_datetime_then_model_is_not_called() -> None:
    runtime = AsyncMock()
    runtime.run = AsyncMock(side_effect=AssertionError("model should not be called"))

    result = await _translator(runtime).datetime_translation_agent(
        "Show Sentinel-2 imagery of Montréal from 2025-07-01 to 2025-08-31",
        ["sentinel-2-l2a"],
    )

    assert result == "2025-07-01/2025-08-31"
    runtime.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_given_static_collection_when_translating_datetime_then_no_filter_is_applied() -> None:
    result = await _translator().datetime_translation_agent(
        "Show Copernicus DEM near Calgary from 2025-07-01 to 2025-08-31",
        ["cop-dem-glo-30"],
    )

    assert result is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "Show Sentinel-2 imagery of Toronto from 2026-06-01 to 2026-08-26",
        "Assess nuclear facility siting near Pickering from 2026-06-01 to 2026-08-26",
    ],
)
async def test_given_no_cloud_wording_when_filtering_clouds_then_model_is_not_called(query) -> None:
    runtime = AsyncMock()
    runtime.run = AsyncMock(side_effect=AssertionError("model should not be called"))

    result = await _translator(runtime).cloud_filtering_agent(query, ["sentinel-2-l2a"])

    assert result is None
    runtime.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_given_clear_sky_request_when_filtering_clouds_then_model_is_consulted() -> None:
    runtime = AsyncMock()
    runtime.run = AsyncMock(
        return_value='{"cloud_intent": "low", "threshold": 25, "reasoning": "clear"}'
    )

    result = await _translator(runtime).cloud_filtering_agent(
        "Show clear Sentinel-2 imagery of Toronto", ["sentinel-2-l2a"]
    )

    runtime.run.assert_awaited_once()
    assert result["threshold"] == 25
