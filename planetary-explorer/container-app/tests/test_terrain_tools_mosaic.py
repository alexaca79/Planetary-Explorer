"""Terrain tools read every intersecting tile and report honest provenance."""

from __future__ import annotations

import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
planetary_computer = pytest.importorskip("planetary_computer")

from geoint import terrain_tools  # noqa: E402
from geoint.dem_geometry import pixel_spacing_meters  # noqa: E402
from raster_test_utils import write_tile  # noqa: E402

JRC_PERIOD = {"start_datetime": "1984-03-01T00:00:00Z", "end_datetime": "2020-12-31T11:59:59Z"}


def item(item_id: str, asset: str, href: str, properties: dict | None = None):
    return SimpleNamespace(
        id=item_id,
        assets={asset: SimpleNamespace(href=href)},
        properties=dict(properties or {}),
        datetime=None,
    )


@pytest.fixture
def catalog(monkeypatch):
    collections: dict[str, list] = {}
    monkeypatch.setattr(planetary_computer, "sign", lambda value: value)
    monkeypatch.setattr(
        terrain_tools,
        "_search_items",
        lambda collection, bbox: list(collections.get(collection, [])),
    )
    return collections


def test_slope_reads_both_dem_tiles_at_a_manitoba_tile_edge(tmp_path, catalog):
    latitude, longitude = 49.848, -99.95  # Brandon: the 5 km box straddles 100 W
    metres_per_degree_lon = pixel_spacing_meters(1.0, 1.0, latitude, geographic=True)[1]

    def grade(lon, lat):
        return 400.0 + 0.05 * (lon + 100.0) * metres_per_degree_lon

    catalog["cop-dem-glo-30"] = [
        item("DEM_W101", "data", write_tile(
            tmp_path / "w.tif", west=-100.2, north=49.95, width=200, height=250,
            res_x=0.001, res_y=0.001, values=grade,
        )),
        item("DEM_W100", "data", write_tile(
            tmp_path / "e.tif", west=-100.0, north=49.95, width=200, height=250,
            res_x=0.001, res_y=0.001, values=grade,
        )),
    ]

    result = json.loads(terrain_tools.get_slope_analysis(latitude, longitude, 5.0))

    assert result["source_item_ids"] == ["DEM_W101", "DEM_W100"]
    assert result["coverage_percent"] == 100.0
    assert result["slope_mean_degrees"] == pytest.approx(math.degrees(math.atan(0.05)), abs=0.1)
    assert result["cell_spacing_meters"]["east_west"] == pytest.approx(
        0.001 * metres_per_degree_lon, abs=0.1
    )
    bbox = terrain_tools._calculate_bbox(latitude, longitude, 5.0)
    full_box_cells = ((bbox[2] - bbox[0]) / 0.001) * ((bbox[3] - bbox[1]) / 0.001)
    assert result["valid_pixel_count"] > 0.95 * full_box_cells


def test_flood_risk_labels_the_period_jrc_actually_observes(tmp_path, catalog):
    def occurrence(lon, lat):
        grid = np.zeros(lon.shape)
        grid[:, 100:120] = 100  # a river inside the Sumas analysis box
        grid[100:105, :] = 255  # JRC "no data" rows inside the box
        return grid

    catalog["jrc-gsw"] = [
        item("130W_50Nv1_3_2020", "occurrence", write_tile(
            tmp_path / "jrc.tif", west=-122.2, north=49.2, width=400, height=400,
            res_x=0.001, res_y=0.001, values=occurrence, dtype="uint8",
        ), JRC_PERIOD),
    ]

    result = json.loads(terrain_tools.analyze_flood_risk(49.06, -122.09, 5.0))

    assert result["data_source"] == "JRC Global Surface Water (1984-2020)"
    assert result["temporal_coverage"] == "1984-03-01/2020-12-31"
    assert result["source_item_ids"] == ["130W_50Nv1_3_2020"]
    assert result["max_water_occurrence_percent"] == 100.0
    assert "source_item_id" not in result


def test_water_setback_uses_latitude_aware_metres_at_the_site(tmp_path, catalog):
    latitude, longitude = 49.0, -122.0

    def occurrence(lon, lat):
        return np.where(lon > -121.99, 90, 0)

    catalog["jrc-gsw"] = [
        item("130W_50Nv1_3_2020", "occurrence", write_tile(
            tmp_path / "jrc.tif", west=-122.2, north=49.2, width=400, height=400,
            res_x=0.001, res_y=0.001, values=occurrence, dtype="uint8",
        ), JRC_PERIOD),
    ]

    result = json.loads(
        terrain_tools.analyze_water_proximity(latitude, longitude, 5.0, required_setback_meters=500.0)
    )

    expected = 0.01 * pixel_spacing_meters(1.0, 1.0, latitude, geographic=True)[1]
    assert result["nearest_water_meters"] == pytest.approx(expected, abs=2.0)
    # A fixed 30 m cell would have reported 300 m and failed the setback.
    assert result["setback_satisfied"] is True
    assert result["cell_spacing_meters"]["east_west"] == pytest.approx(expected / 10, abs=0.1)


def test_land_cover_uses_newest_product_and_northern_classes(tmp_path, catalog):
    def tree_cover(lon, lat):
        return np.full(lon.shape, 10)

    def moss_and_lichen(lon, lat):
        return np.full(lon.shape, 100)

    catalog["esa-worldcover"] = [
        item("ESA_WorldCover_10m_2020_v100_N63W069", "map", write_tile(
            tmp_path / "wc2020.tif", west=-68.8, north=63.9, width=600, height=300,
            res_x=0.001, res_y=0.001, values=tree_cover, dtype="uint8", nodata=0,
        ), {"start_datetime": "2020-01-01T00:00:00Z", "end_datetime": "2020-12-31T23:59:59Z"}),
        item("ESA_WorldCover_10m_2021_v200_N63W069", "map", write_tile(
            tmp_path / "wc2021.tif", west=-68.8, north=63.9, width=600, height=300,
            res_x=0.001, res_y=0.001, values=moss_and_lichen, dtype="uint8", nodata=0,
        ), {"start_datetime": "2021-01-01T00:00:00Z", "end_datetime": "2021-12-31T23:59:59Z"}),
    ]

    result = json.loads(terrain_tools.analyze_environmental_sensitivity(63.7467, -68.517, 5.0))

    assert result["source_item_ids"] == ["ESA_WorldCover_10m_2021_v200_N63W069"]
    assert result["data_source"] == "ESA WorldCover 2021 (10m resolution)"
    assert result["dominant_land_cover"] == "Moss And Lichen"
    assert result["land_cover_breakdown_percent"] == {"moss_and_lichen": 100.0}


def test_missing_dem_returns_the_existing_error(catalog):
    result = json.loads(terrain_tools.get_slope_analysis(49.0, -122.0, 5.0))

    assert result == {"error": "No DEM data available"}


def test_elevation_reports_mosaic_provenance(tmp_path, catalog):
    catalog["cop-dem-glo-30"] = [
        item("DEM", "data", write_tile(
            tmp_path / "dem.tif", west=-122.2, north=49.2, width=400, height=400,
            res_x=0.001, res_y=0.001, values=lambda lon, lat: 10.0 + 0.0 * lon,
        )),
    ]

    result = json.loads(terrain_tools.get_elevation_analysis(49.06, -122.09, 5.0))

    assert result["elevation_mean_meters"] == 10.0
    assert result["terrain_type"] == "flat plains"
    assert result["data_source"] == "Copernicus DEM GLO-30"
    assert result["coverage_percent"] == 100.0
