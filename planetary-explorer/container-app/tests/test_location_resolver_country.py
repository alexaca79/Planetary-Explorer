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
    # Azure Maps Search v1 rejects "PopulatedPlace" with HTTP 400.
    assert captured["params"]["entityType"] == "Municipality,MunicipalitySubdivision"


def _maps_resolver() -> EnhancedLocationResolver:
    resolver = object.__new__(EnhancedLocationResolver)
    resolver.logger = logging.getLogger(__name__)
    resolver.cache = LocationCache()
    resolver.azure_maps_key = "test-key"
    resolver.azure_maps_use_managed_identity = False
    resolver._token_provider = None
    resolver.azure_maps_client_id = None
    return resolver


# Shape of the live Azure Maps result for Iqaluit on 2026-09-30: the position
# is correct, but the viewport spans about 49 x 32 degrees of Nunavut.
IQALUIT_RESULT = {
    "type": "Geography",
    "entityType": "Municipality",
    "score": 6.62,
    "address": {
        "municipality": "Iqaluit",
        "countryCode": "CA",
        "countrySubdivision": "NU",
        "freeformAddress": "Iqaluit NU",
    },
    "position": {"lat": 63.751, "lon": -68.523},
    "viewport": {
        "topLeftPoint": {"lon": -109.85, "lat": 83.11},
        "btmRightPoint": {"lon": -61.18, "lat": 51.58},
    },
}


def test_given_municipality_with_territory_viewport_when_extracting_then_box_surrounds_position() -> None:
    bbox = _maps_resolver()._extract_azure_bounds(IQALUIT_RESULT)

    assert (bbox[1] + bbox[3]) / 2 == pytest.approx(63.751, abs=1e-6)
    assert (bbox[0] + bbox[2]) / 2 == pytest.approx(-68.523, abs=1e-6)
    assert bbox[3] - bbox[1] == pytest.approx(0.2)


def test_given_city_viewport_containing_position_when_extracting_then_viewport_is_kept() -> None:
    result = {
        "type": "Geography",
        "entityType": "Municipality",
        "position": {"lat": 42.984, "lon": -81.248},
        "viewport": {
            "topLeftPoint": {"lon": -81.41, "lat": 43.11},
            "btmRightPoint": {"lon": -81.09, "lat": 42.86},
        },
    }

    assert _maps_resolver()._extract_azure_bounds(result) == [-81.41, 42.86, -81.09, 43.11]


def test_given_large_landmark_viewport_when_extracting_then_it_is_not_shrunk() -> None:
    result = {
        "type": "POI",
        "poi": {"name": "Lake Superior"},
        "position": {"lat": 47.7, "lon": -87.5},
        "viewport": {
            "topLeftPoint": {"lon": -92.1, "lat": 49.0},
            "btmRightPoint": {"lon": -84.4, "lat": 46.4},
        },
    }

    assert _maps_resolver()._extract_azure_bounds(result) == [-92.1, 46.4, -84.4, 49.0]


@pytest.mark.asyncio
async def test_given_iqaluit_when_resolving_then_navigation_centre_is_the_city(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        location_resolver.aiohttp,
        "ClientSession",
        lambda: _Session(captured, _Response({"results": [IQALUIT_RESULT]})),
    )

    bbox = await _maps_resolver().resolve_location_to_bbox("Iqaluit, Nunavut")

    assert (bbox[1] + bbox[3]) / 2 == pytest.approx(63.751, abs=0.01)
    assert (bbox[0] + bbox[2]) / 2 == pytest.approx(-68.523, abs=0.01)
    assert captured["params"]["countrySet"] == "CA"


@pytest.mark.asyncio
async def test_given_canadian_name_when_address_fallback_runs_then_search_is_limited_to_canada(
    monkeypatch,
) -> None:
    captured = {}
    monkeypatch.setattr(
        location_resolver.aiohttp,
        "ClientSession",
        lambda: _Session(captured, _Response({"results": [IQALUIT_RESULT]})),
    )

    await _maps_resolver()._azure_maps_address_search("Iqaluit, Nunavut, Canada")

    assert captured["params"]["countrySet"] == "CA"


@pytest.mark.asyncio
@pytest.mark.parametrize(("confidence", "accepted"), [(0.605, False), (0.956, True), (None, True)])
async def test_given_address_fallback_when_match_confidence_is_low_then_result_is_rejected(
    monkeypatch,
    confidence,
    accepted,
) -> None:
    result = {
        "type": "Geography",
        "entityType": "Municipality",
        "position": {"lat": 35.468, "lon": -97.521},
        "viewport": {
            "topLeftPoint": {"lon": -97.84, "lat": 35.68},
            "btmRightPoint": {"lon": -97.12, "lat": 35.29},
        },
    }
    if confidence is not None:
        result["matchConfidence"] = {"score": confidence}
    monkeypatch.setattr(
        location_resolver.aiohttp,
        "ClientSession",
        lambda: _Session({}, _Response({"results": [result]})),
    )

    bbox = await _maps_resolver()._azure_maps_address_search("Qwertyuiopville city USA")

    assert (bbox is not None) is accepted


@pytest.mark.asyncio
@pytest.mark.parametrize("search", ["_azure_maps_fuzzy_search", "_azure_maps_with_population_priority"])
async def test_given_unqualified_city_when_searching_municipalities_then_no_us_only_filter_is_sent(
    monkeypatch,
    search,
) -> None:
    captured = {}
    monkeypatch.setattr(
        location_resolver.aiohttp,
        "ClientSession",
        lambda: _Session(captured),
    )

    bbox = await getattr(_maps_resolver(), search)("Springfield")

    assert bbox is None
    assert captured == {}


@pytest.mark.asyncio
async def test_given_unqualified_canadian_capital_when_fuzzy_searching_then_canada_is_searched(
    monkeypatch,
) -> None:
    captured = {}
    monkeypatch.setattr(
        location_resolver.aiohttp,
        "ClientSession",
        lambda: _Session(captured),
    )

    await _maps_resolver()._azure_maps_fuzzy_search("Ottawa")

    assert captured["params"]["countrySet"] == "CA"


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