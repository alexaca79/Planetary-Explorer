"""Tests for deterministic post-load STAC asset inspection."""

from datetime import date

import pytest

import pipeline.stac_inspection as stac_inspection
from pipeline.stac_inspection import (
    apply_collection_inspection_overrides,
    build_collection_asset_inspection_summary,
)


def test_given_bc_pin_when_translator_invents_other_location_then_point_load_stays_at_pin() -> None:
    # Arrange
    translated = {
        "collections": ["sentinel-2-l2a"],
        "bbox": [-118.67, 33.7, -118.16, 34.34],
        "datetime": "2026-08-28",
        "location_name": "Los Angeles",
    }

    # Act
    result = stac_inspection.apply_pin_imagery_overrides(
        stac_params=translated,
        query="Show Sentinel-2 imagery at this point on 2026-08-28.",
        pin={"lat": 49.432296, "lng": -122.482823},
    )

    # Assert
    west, south, east, north = result["bbox"]
    assert (west + east) / 2 == pytest.approx(-122.482823)
    assert (south + north) / 2 == pytest.approx(49.432296)
    assert east - west < 0.1
    assert result["datetime"] == "2026-08-28"
    assert translated["location_name"] == "Los Angeles"


def test_given_nearest_date_when_searching_at_pin_then_expands_window_without_default_cloud_filter() -> None:
    # Arrange
    translated = {
        "collections": ["sentinel-2-l2a"],
        "datetime": "2026-08-28",
        "query": {"eo:cloud_cover": {"lt": 20}, "platform": {"eq": "sentinel-2a"}},
    }

    # Act
    result = stac_inspection.apply_pin_imagery_overrides(
        stac_params=translated,
        query="Show imagery at point on 2026-08-28. Use the nearest available date.",
        pin={"lat": 49.432296, "lng": -122.482823},
        today=date(2026, 9, 9),
    )

    # Assert
    assert result["datetime"] == "2026-08-14/2026-09-09"
    assert result["query"] == {"platform": {"eq": "sentinel-2a"}}
    assert result["limit"] == 200
    assert translated["query"]["eo:cloud_cover"] == {"lt": 20}


def test_given_explicit_cloud_requirement_when_searching_nearest_then_preserves_filter() -> None:
    # Arrange
    translated = {"collections": ["sentinel-2-l2a"], "query": {"eo:cloud_cover": {"lt": 10}}}

    # Act
    result = stac_inspection.apply_pin_imagery_overrides(
        stac_params=translated,
        query="Show the nearest clear imagery here to August 28, 2026.",
        pin={"lat": 49.432296, "lng": -122.482823},
        today=date(2026, 9, 9),
    )

    # Assert
    assert result["query"] == translated["query"]
    assert result["datetime"] == "2026-08-14/2026-09-09"


def test_given_explicit_region_when_applying_point_overrides_then_region_is_preserved() -> None:
    # Arrange
    translated = {"collections": ["sentinel-2-l2a"], "bbox": [-124, 48, -120, 51]}

    # Act
    result = stac_inspection.apply_pin_imagery_overrides(
        stac_params=translated,
        query="Show imagery over the entire map around this pin.",
        pin={"lat": 49.432296, "lng": -122.482823},
    )

    # Assert
    assert result == translated


def test_given_pin_when_applying_inspection_overrides_then_collection_and_aoi_are_pinned() -> (
    None
):
    # Arrange
    translated = {
        "collections": ["sentinel-2-l2a"],
        "bbox": [-118.67, 33.7, -118.16, 34.34],
        "datetime": "2026-07-04",
        "location_name": "la",
    }

    # Act
    overridden = apply_collection_inspection_overrides(
        stac_params=translated,
        collection_id="hls2-s30",
        pin={"lat": 50.268, "lng": -89.8572},
    )

    # Assert
    assert overridden["collections"] == ["hls2-s30"]
    assert overridden["datetime"] == "2026-07-04"
    assert overridden["location_name"] == "Pinned location (50.2680, -89.8572)"
    assert overridden["bbox"] == pytest.approx(
        [-89.9706, 50.1955, -89.7438, 50.3405],
        abs=0.0001,
    )
    assert translated["collections"] == ["sentinel-2-l2a"]


def test_given_hls_scene_when_building_asset_inspection_then_reports_actual_fire_bands() -> (
    None
):
    # Arrange
    features = [
        {
            "id": "HLS.S30.T16UEA.2026185T170901.v2.0",
            "collection": "hls2-s30",
            "properties": {"datetime": "2026-07-04T17:09:44Z"},
            "assets": {
                "B02": {"href": "https://example.test/B02.tif"},
                "B04": {"href": "https://example.test/B04.tif"},
                "B8A": {"href": "https://example.test/B8A.tif"},
                "B12": {"href": "https://example.test/B12.tif"},
                "Fmask": {"href": "https://example.test/Fmask.tif"},
            },
        }
    ]

    # Act
    summary = build_collection_asset_inspection_summary(
        features=features,
        collection_id="hls2-s30",
        render_assets=["B12", "B8A", "B04"],
        render_summary="Displaying 1 HLS image.",
        stac_mode="public",
    )

    # Assert
    assert "`B12` (SWIR2) / `B8A` (narrow NIR) / `B04` (red)" in summary
    assert "HLS.S30.T16UEA.2026185T170901.v2.0" in summary
    assert "2026-07-04" in summary
    assert "`Fmask`" in summary
    assert "Public Planetary Computer" in summary


def test_given_other_collection_items_when_building_inspection_then_ignores_their_assets() -> (
    None
):
    # Arrange
    features = [
        {
            "id": "requested-scene",
            "collection": "hls2-s30",
            "properties": {},
            "assets": {"B04": {}, "B8A": {}, "B12": {}},
        },
        {
            "id": "other-scene",
            "collection": "other-collection",
            "properties": {},
            "assets": {"secret": {}},
        },
    ]

    # Act
    summary = build_collection_asset_inspection_summary(
        features=features,
        collection_id="hls2-s30",
        render_assets=None,
        render_summary="Displaying imagery.",
        stac_mode="pro",
    )

    # Assert
    assert "Available recipe" in summary
    assert "`secret`" not in summary
    assert "MPC Pro" in summary


def test_given_pro_remapped_collection_when_building_inspection_then_resolved_assets_are_reported() -> (
    None
):
    # Arrange
    features = [
        {
            "id": "tenant-fire-scene",
            "collection": "tenant-hls-fire",
            "properties": {"datetime": "2026-07-04T17:09:44Z"},
            "assets": {"B04": {}, "B8A": {}, "B12": {}, "Fmask": {}},
        }
    ]

    # Act
    summary = build_collection_asset_inspection_summary(
        features=features,
        collection_id="hls2-s30",
        render_assets=["B12", "B8A", "B04"],
        render_summary="Displaying tenant imagery.",
        stac_mode="pro",
    )

    # Assert
    assert "**Available assets**" in summary
    assert "`tenant-hls-fire` (requested as `hls2-s30`)" in summary
    assert "`B12` (SWIR2) / `B8A` (narrow NIR) / `B04` (red)" in summary
