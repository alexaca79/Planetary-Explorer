"""Country-routing regressions for the enhanced location resolver."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

import location_resolver
from location_resolver import EnhancedLocationResolver, LocationCache
from semantic_translator import SemanticQueryTranslator


class _Response:
    status = 200

    def __init__(self, payload=None):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def json(self):
        if self.payload is not None:
            return self.payload
        return {
            "results": [
                {
                    "score": 9.8,
                    "entityType": "Municipality",
                    "address": {
                        "municipality": "Regina",
                        "countryCode": "CA",
                        "countrySubdivision": "Saskatchewan",
                        "freeformAddress": "Regina, Saskatchewan",
                    },
                    "viewport": {
                        "topLeftPoint": {"lon": -104.75, "lat": 50.53},
                        "btmRightPoint": {"lon": -104.46, "lat": 50.36},
                    },
                }
            ]
        }


class _Session:
    def __init__(self, captured, response=None):
        self.captured = captured
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def get(self, url, *, params, headers):
        self.captured.update({"url": url, "params": params, "headers": headers})
        return self.response or _Response()


@pytest.mark.asyncio
async def test_given_canadian_city_when_fuzzy_searching_then_country_filter_is_canada(
    monkeypatch,
) -> None:
    captured = {}
    resolver = object.__new__(EnhancedLocationResolver)
    resolver.logger = logging.getLogger(__name__)
    resolver.azure_maps_key = "test-key"
    resolver.azure_maps_use_managed_identity = False
    resolver._token_provider = None
    resolver.azure_maps_client_id = None
    monkeypatch.setattr(
        location_resolver.aiohttp,
        "ClientSession",
        lambda: _Session(captured),
    )

    bbox = await resolver._azure_maps_fuzzy_search("Regina, Canada")

    assert captured["params"]["countrySet"] == "CA"
    assert captured["params"]["query"] == "Regina, Canada"
    assert bbox == [-104.75, 50.36, -104.46, 50.53]


@pytest.mark.asyncio
async def test_given_generated_city_query_when_fuzzy_searching_then_city_filter_is_kept(
    monkeypatch,
) -> None:
    captured = {}
    resolver = object.__new__(EnhancedLocationResolver)
    resolver.logger = logging.getLogger(__name__)
    resolver.azure_maps_key = "test-key"
    resolver.azure_maps_use_managed_identity = False
    resolver._token_provider = None
    resolver.azure_maps_client_id = None
    monkeypatch.setattr(
        location_resolver.aiohttp,
        "ClientSession",
        lambda: _Session(captured),
    )

    await resolver._azure_maps_fuzzy_search(
        "Regina, Saskatchewan, Canada city",
        "city",
    )

    assert captured["params"]["countrySet"] == "CA"
    assert captured["params"]["entityType"] == "Municipality,PopulatedPlace"


def test_given_qualified_canadian_city_when_preprocessing_then_us_bias_is_omitted() -> None:
    resolver = object.__new__(EnhancedLocationResolver)

    queries = resolver._preprocess_location_query("Regina, Canada", "city")

    assert queries
    assert all("usa" not in query.casefold() for query in queries)
    assert all("united states" not in query.casefold() for query in queries)


@pytest.mark.asyncio
async def test_given_city_viewport_when_resolving_then_small_valid_bbox_is_retained() -> None:
    resolver = object.__new__(EnhancedLocationResolver)
    resolver.logger = logging.getLogger(__name__)
    resolver._azure_maps_fuzzy_search = AsyncMock(
        return_value=[-104.75, 50.36, -104.46, 50.53]
    )
    resolver._azure_maps_with_population_priority = AsyncMock(return_value=None)
    resolver._azure_maps_address_search = AsyncMock(return_value=None)
    resolver._is_azure_maps_configured = lambda: True

    bbox = await resolver._strategy_azure_maps(
        "Regina, Saskatchewan, Canada",
        "region",
    )

    assert bbox == [-104.75, 50.36, -104.46, 50.53]
    resolver._azure_maps_address_search.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("declared_type", ["region", "country"])
async def test_given_qualified_city_when_resolving_variants_then_city_type_is_preserved(
    declared_type,
) -> None:
    resolver = object.__new__(EnhancedLocationResolver)
    resolver.logger = logging.getLogger(__name__)
    resolver.cache = LocationCache()
    resolver._is_azure_maps_configured = lambda: True
    resolver._strategy_azure_maps = AsyncMock(
        return_value=[-104.75, 50.36, -104.46, 50.53]
    )

    bbox = await resolver.resolve_location_to_bbox(
        "Regina, Saskatchewan, Canada",
        declared_type,
    )

    assert bbox == [-104.75, 50.36, -104.46, 50.53]
    assert resolver._strategy_azure_maps.await_args.args[1] == "city"


def test_given_canadian_province_when_normalizing_then_it_remains_administrative() -> None:
    resolver = object.__new__(EnhancedLocationResolver)

    assert resolver._normalize_location_type("Saskatchewan, Canada", "country") == "state"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("location", "expected_bbox"),
    [
        ("Calgary, Alberta, Canada", [-114.32, 50.84, -113.83, 51.21]),
        ("Lake Ontario, Canada", [-79.80, 43.10, -76.00, 44.30]),
        ("Western Canada", [-139.06, 48.30, -101.36, 60.00]),
        ("Lytton, British Columbia, Canada", [-121.65, 50.18, -121.50, 50.28]),
    ],
)
async def test_given_get_started_place_when_resolving_then_stored_bounds_win(
    location,
    expected_bbox,
) -> None:
    # Arrange
    resolver = object.__new__(EnhancedLocationResolver)
    resolver.logger = logging.getLogger(__name__)
    resolver.cache = LocationCache()

    # Act
    bbox = await resolver.resolve_location_to_bbox(location, "region")

    # Assert
    assert bbox == expected_bbox


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "location",
    [
        "London, Ontario, Canada",
        "London, Ontario",
        "London, ON",
        "London Ontario",
        "London ON",
    ],
)
async def test_given_canadian_london_when_resolving_then_foreign_stored_place_is_rejected(
    monkeypatch,
    location,
) -> None:
    captured = {}
    response = _Response({
        "results": [{
            "score": 9.8,
            "entityType": "Municipality",
            "address": {
                "municipality": "London",
                "countryCode": "CA",
                "countrySubdivision": "Ontario",
                "freeformAddress": "London, Ontario, Canada",
            },
            "viewport": {
                "topLeftPoint": {"lon": -81.4, "lat": 43.1},
                "btmRightPoint": {"lon": -81.1, "lat": 42.8},
            },
        }],
    })
    resolver = object.__new__(EnhancedLocationResolver)
    resolver.logger = logging.getLogger(__name__)
    resolver.cache = LocationCache()
    resolver.azure_maps_key = "test-key"
    resolver.azure_maps_use_managed_identity = False
    resolver._token_provider = None
    resolver.azure_maps_client_id = None
    monkeypatch.setattr(
        location_resolver.aiohttp,
        "ClientSession",
        lambda: _Session(captured, response),
    )

    bbox = await resolver.resolve_location_to_bbox(location)

    assert bbox == [-81.4, 42.8, -81.1, 43.1]
    assert captured["params"]["countrySet"] == "CA"


@pytest.mark.asyncio
@pytest.mark.parametrize("qualifier", ["region", "code"])
@pytest.mark.parametrize("entry_point", ["resolver", "query_builder"])
async def test_given_canadian_place_when_geocoding_then_named_point_stays_local(
    monkeypatch,
    canadian_location,
    qualifier,
    entry_point,
) -> None:
    latitude = canadian_location["latitude"]
    longitude = canadian_location["longitude"]
    captured = {}
    response = _Response({
        "results": [{
            "score": 9.8,
            "entityType": "Municipality",
            "address": {
                "municipality": canadian_location["name"],
                "countryCode": "CA",
                "countrySubdivision": canadian_location["region"],
            },
            "viewport": {
                "topLeftPoint": {"lon": longitude - 0.05, "lat": latitude + 0.05},
                "btmRightPoint": {"lon": longitude + 0.05, "lat": latitude - 0.05},
            },
        }],
    })
    resolver = object.__new__(EnhancedLocationResolver)
    resolver.logger = logging.getLogger(__name__)
    resolver.cache = LocationCache()
    resolver.azure_maps_key = "test-key"
    resolver.azure_maps_use_managed_identity = False
    resolver._token_provider = None
    resolver.azure_maps_client_id = None
    monkeypatch.setattr(
        location_resolver.aiohttp,
        "ClientSession",
        lambda: _Session(captured, response),
    )

    place = f"{canadian_location['name']}, {canadian_location[qualifier]}"
    if entry_point == "query_builder":
        translator = object.__new__(SemanticQueryTranslator)
        translator._agent_runtime_initialized = True
        translator.agent_runtime = None
        translator.location_resolver = resolver
        translator.location_cache = LocationCache()
        result = await translator.build_stac_query_agent(
            f"Show HLS S30 imagery over {place} from 2026-06-01 to 2026-08-26",
            ["hls2-s30"],
        )
        bbox = result.get("bbox")
    else:
        bbox = await resolver.resolve_location_to_bbox(place)

    assert bbox is not None
    assert abs((bbox[0] + bbox[2]) / 2 - longitude) < 0.5
    assert abs((bbox[1] + bbox[3]) / 2 - latitude) < 0.5
    if captured:
        assert captured["params"]["countrySet"] == "CA"


@pytest.mark.asyncio
async def test_given_portland_ontario_when_geocoding_then_us_city_inside_canada_envelope_is_rejected(
    monkeypatch,
) -> None:
    captured = {}
    response = _Response({
        "results": [{
            "score": 9.8,
            "entityType": "Municipality",
            "address": {"municipality": "Portland", "countryCode": "CA"},
            "viewport": {
                "topLeftPoint": {"lon": -76.25, "lat": 44.75},
                "btmRightPoint": {"lon": -76.15, "lat": 44.65},
            },
        }],
    })
    resolver = object.__new__(EnhancedLocationResolver)
    resolver.logger = logging.getLogger(__name__)
    resolver.cache = LocationCache()
    resolver.azure_maps_key = "test-key"
    resolver.azure_maps_use_managed_identity = False
    resolver._token_provider = None
    resolver.azure_maps_client_id = None
    monkeypatch.setattr(
        location_resolver.aiohttp,
        "ClientSession",
        lambda: _Session(captured, response),
    )

    bbox = await resolver.resolve_location_to_bbox("Portland, Ontario, Canada")

    assert bbox == [-76.25, 44.65, -76.15, 44.75]