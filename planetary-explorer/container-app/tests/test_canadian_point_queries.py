"""Coordinate-first STAC query contracts for Canadian Get Started workflows."""

from __future__ import annotations

import pytest

from semantic_translator import SemanticQueryTranslator


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "coordinates",
    [
        "latitude 82.5018 N, longitude 62.3481 W",
        "longitude -62.3481, latitude 82.5018",
        "lat=82.5018; lng=-62.3481",
        "82.5018 N, 62.3481 W",
        "82.5018, -62.3481",
        "82.5018, 62.3481 W",
        "latitude 82.5018, longitude -62.3481.",
        "82.5018, -62.3481.",
    ],
)
async def test_given_arctic_coordinates_when_building_query_then_exact_point_is_retained(
    coordinates,
) -> None:
    translator = object.__new__(SemanticQueryTranslator)
    translator._agent_runtime_initialized = True
    translator.agent_runtime = None

    result = await translator.build_stac_query_agent(
        f"Show HLS S30 imagery at {coordinates} "
        "from 2026-06-01 to 2026-08-26",
        ["hls2-s30"],
    )

    assert result.get("bbox") == [-62.3581, 82.4918, -62.3381, 82.5118]
    assert result["datetime"] == "2026-06-01/2026-08-26"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "coordinates",
    [
        "latitude 95, longitude -123",
        "latitude 82.5018, longitude -200",
        "latitude NaN, longitude -62.3481",
        "latitude -82.5018 N, longitude -62.3481",
        "latitude 82.5018 E, longitude -62.3481",
        "latitude 82 degrees 30 minutes, longitude -62.3481",
        "latitude 82.5018, longitude -62.3481, latitude 63.7467",
    ],
)
async def test_given_invalid_coordinates_when_building_query_then_clarification_has_no_bounds(
    coordinates,
) -> None:
    translator = object.__new__(SemanticQueryTranslator)
    translator._agent_runtime_initialized = True
    translator.agent_runtime = None

    result = await translator.build_stac_query_agent(
        f"Show HLS S30 imagery at {coordinates} "
        "from 2026-06-01 to 2026-08-26",
        ["hls2-s30"],
    )

    assert result.get("error") == "LOCATION_REQUIRED"
    assert "bbox" not in result
    assert "latitude" in result["message"]
    assert "longitude" in result["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "collection",
    [
        "sentinel-2-l2a",
        "hls2-s30",
        "landsat-c2-l2",
        "modis-14A1-061",
        "modis-13Q1-061",
        "modis-17A2H-061",
        "modis-10A1-061",
        "cop-dem-glo-30",
        "sentinel-1-rtc",
    ],
)
@pytest.mark.parametrize(
    "coordinate_format",
    [
        "latitude {latitude}, longitude {longitude}",
        "lng={longitude}; lat={latitude}",
        "{latitude} N, {west_longitude} W",
        "{latitude}, {longitude}",
    ],
)
async def test_given_canadian_point_when_building_playbook_query_then_location_and_dates_are_preserved(
    canadian_location,
    collection,
    coordinate_format,
) -> None:
    translator = object.__new__(SemanticQueryTranslator)
    translator._agent_runtime_initialized = True
    translator.agent_runtime = None
    latitude = canadian_location["latitude"]
    longitude = canadian_location["longitude"]
    coordinates = coordinate_format.format(
        latitude=latitude,
        longitude=longitude,
        west_longitude=abs(longitude),
    )

    result = await translator.build_stac_query_agent(
        f"Show collection {collection} at {coordinates} "
        "from 2025-02-01 to 2025-02-28",
        [collection],
    )

    west, south, east, north = result["bbox"]
    assert ((south + north) / 2, (west + east) / 2) == pytest.approx(
        (latitude, longitude), abs=0.000001
    )
    assert west < longitude < east and south < latitude < north
    assert east - west < 0.05 and north - south < 0.05
    assert result["collections"] == [collection]
    if collection == "cop-dem-glo-30":
        assert "datetime" not in result
    else:
        assert result["datetime"] == "2025-02-01/2025-02-28"