"""Canadian place names with accents or no qualifier keep their location."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from location_resolver import EnhancedLocationResolver
from semantic_translator import SemanticQueryTranslator


def _translator() -> SemanticQueryTranslator:
    translator = object.__new__(SemanticQueryTranslator)
    translator._agent_runtime_initialized = True
    translator.agent_runtime = None
    return translator


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Québec City", "CA"),
        ("Quebec City", "CA"),
        ("Trois-Rivières", "CA"),
        ("Montréal", "CA"),
        ("Ottawa", "CA"),
        ("St. John's", "CA"),
        ("Val-d'Or", "CA"),
        ("Sept-Îles", "CA"),
        ("Iqaluit", "CA"),
        ("Ottawa, Illinois", "US"),
        ("Toronto, Ohio", "US"),
        ("London", "US"),
        ("Kingston", "US"),
        ("Springfield", "US"),
    ],
)
def test_given_unqualified_place_when_choosing_country_then_canadian_names_stay_in_canada(
    name, expected
) -> None:
    assert EnhancedLocationResolver._azure_maps_country_context(name)[0] == expected


def test_given_unqualified_canadian_city_when_preprocessing_then_no_usa_suffix_is_added() -> None:
    resolver = object.__new__(EnhancedLocationResolver)

    assert resolver._preprocess_location_query("Québec City", "city") == ["Québec City, Canada"]


@pytest.mark.asyncio
async def test_given_accented_stored_city_when_resolving_then_stored_bounds_are_used() -> None:
    resolver = object.__new__(EnhancedLocationResolver)
    resolver.logger = __import__("logging").getLogger(__name__)
    resolver.cache = __import__("location_resolver").LocationCache()

    bbox = await resolver.resolve_location_to_bbox("Montréal", "city")

    assert bbox == EnhancedLocationResolver.STORED_LOCATIONS["montreal"]


def test_given_accented_query_when_fast_matching_then_stored_city_is_found() -> None:
    result = _translator()._fast_location_keyword_match(
        "Show Sentinel-2 imagery of Montréal from 2025-07-01 to 2025-08-31"
    )

    assert result == "Montreal"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Show Sentinel-2 imagery of Trois-Rivières from 2025-07-01 to 2025-08-31", "Trois-Rivières"),
        ("Show Landsat imagery of Zürich from 2025-06-01 to 2025-06-30", "Zürich"),
        ("Show Sentinel-2 imagery over St. John's", "St. John's"),
    ],
)
async def test_given_unicode_place_when_basic_extraction_runs_then_name_is_kept(query, expected) -> None:
    assert await _translator()._extract_location_basic(query) == expected


@pytest.mark.asyncio
async def test_given_canadian_place_when_extracting_location_then_model_call_is_skipped() -> None:
    translator = _translator()
    translator._ensure_agent_runtime_initialized = AsyncMock(
        side_effect=AssertionError("model runtime should not be needed")
    )

    result = await translator.location_extraction_agent(
        "Show Sentinel-2 imagery of Trois-Rivières from 2025-07-01 to 2025-08-31"
    )

    assert result["location"]["name"] == "Trois-Rivières"


@pytest.mark.asyncio
async def test_given_unresolved_place_when_translating_then_no_global_search_is_built() -> None:
    translator = _translator()
    translator.collection_mapping_agent = AsyncMock(return_value=["sentinel-2-l2a"])
    translator.build_stac_query_agent = AsyncMock(
        return_value={"collections": ["sentinel-2-l2a"], "datetime": "2025-07-01/2025-08-31"}
    )

    result = await translator.translate_query(
        "Show Sentinel-2 imagery of Nowhereville from 2025-07-01 to 2025-08-31",
        skip_intent_classification=True,
        pre_classified_intent="stac_search",
    )

    assert result["error"] == "LOCATION_REQUIRED"
    assert "bbox" not in result


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Show Sentinel-2 imagery from 2025-07-01 to 2025-08-31", False),
        ("Show Landsat Collection 2 Level-2 imagery", False),
        ("Show Copernicus DEM elevation", False),
        ("Show Sentinel-2 imagery of Montréal", True),
        ("Show elevation map of Mount Rainier, Washington", True),
        ("Show Mount Rainier", True),
        ("Show Québec, Canada", True),
    ],
)
def test_given_query_when_checking_for_a_named_place_then_dataset_names_are_not_places(
    query, expected
) -> None:
    from semantic_translator import _mentions_explicit_place

    assert _mentions_explicit_place(query) is expected


@pytest.mark.asyncio
async def test_given_session_bbox_when_query_has_no_place_then_session_location_is_used() -> None:
    translator = _translator()
    translator.query_checker = None
    translator.collection_mapping_agent = AsyncMock(return_value=["sentinel-2-l2a"])
    translator.build_stac_query_agent = AsyncMock(
        return_value={"collections": ["sentinel-2-l2a"], "datetime": "2025-07-01/2025-08-31"}
    )

    result = await translator.translate_query(
        "Show Sentinel-2 imagery from 2025-07-01 to 2025-08-31",
        session_bbox=[-73.7, 45.4, -73.5, 45.6],
        skip_intent_classification=True,
        pre_classified_intent="stac_search",
    )

    assert result.get("error") != "LOCATION_REQUIRED"
    assert result.get("bbox") == [-73.7, 45.4, -73.5, 45.6]
