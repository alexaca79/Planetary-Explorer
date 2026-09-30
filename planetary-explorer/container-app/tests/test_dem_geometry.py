"""Metric slope, aspect, and terrain-tool accuracy at Canadian latitudes."""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from geoint.dem_geometry import pixel_spacing_meters, slope_aspect_degrees

ARC_SECOND = 1.0 / 3600.0


def _geographic_plane(
    latitude: float,
    res_x_arcsec: float,
    *,
    north_slope_degrees: float = 0.0,
    east_slope_degrees: float = 0.0,
    size: int = 64,
) -> tuple[np.ndarray, tuple[float, float]]:
    """Build a north-up geographic DEM plane with known slopes."""
    row_m, column_m = pixel_spacing_meters(
        res_x_arcsec * ARC_SECOND, ARC_SECOND, latitude, geographic=True
    )
    rows, columns = np.mgrid[0:size, 0:size]
    northing = (size - 1 - rows) * row_m
    easting = columns * column_m
    elevation = (
        100.0
        + northing * math.tan(math.radians(north_slope_degrees))
        + easting * math.tan(math.radians(east_slope_degrees))
    )
    return elevation, (row_m, column_m)


@pytest.mark.parametrize(
    ("place", "latitude", "res_x_arcsec", "expected_row_m", "expected_column_m"),
    [
        ("Sumas Prairie BC", 49.06, 1.0, 30.9, 20.3),
        ("Prince George BC", 53.92, 1.5, 30.9, 27.4),
        ("Whitehorse YT", 60.72, 2.0, 30.9, 30.3),
        ("Resolute NU", 74.70, 3.0, 31.0, 24.6),
        ("Alert NU", 82.50, 5.0, 31.0, 20.2),
    ],
)
def test_given_copernicus_grid_when_measuring_cells_then_axes_use_metric_spacing(
    place: str,
    latitude: float,
    res_x_arcsec: float,
    expected_row_m: float,
    expected_column_m: float,
) -> None:
    # Act
    row_m, column_m = pixel_spacing_meters(
        res_x_arcsec * ARC_SECOND, ARC_SECOND, latitude, geographic=True
    )

    # Assert
    assert row_m == pytest.approx(expected_row_m, abs=0.15), place
    assert column_m == pytest.approx(expected_column_m, abs=0.15), place


def test_given_projected_grid_when_measuring_cells_then_resolution_is_used_directly() -> None:
    # Act
    spacing = pixel_spacing_meters(10.0, -10.0, 45.42, geographic=False)

    # Assert
    assert spacing == (10.0, 10.0)


@pytest.mark.parametrize(
    ("latitude", "res_x_arcsec"),
    [(49.06, 1.0), (53.92, 1.5), (60.72, 2.0), (82.50, 5.0)],
)
def test_given_north_rising_plane_when_sloped_then_true_slope_and_south_aspect(
    latitude: float,
    res_x_arcsec: float,
) -> None:
    # Arrange
    elevation, spacing = _geographic_plane(
        latitude, res_x_arcsec, north_slope_degrees=10.0
    )

    # Act
    slope, aspect = slope_aspect_degrees(elevation, *spacing)

    # Assert
    assert float(np.mean(slope)) == pytest.approx(10.0, abs=0.05)
    assert float(np.median(aspect)) == pytest.approx(180.0, abs=0.5)


def test_given_east_rising_plane_when_sloped_then_aspect_faces_west() -> None:
    # Arrange
    elevation, spacing = _geographic_plane(62.454, 2.0, east_slope_degrees=4.0)

    # Act
    slope, aspect = slope_aspect_degrees(elevation, *spacing)

    # Assert
    assert float(np.mean(slope)) == pytest.approx(4.0, abs=0.05)
    assert float(np.median(aspect)) == pytest.approx(270.0, abs=0.5)


def test_given_nodata_cells_when_sloped_then_invalid_neighbours_are_excluded() -> None:
    # Arrange
    elevation, spacing = _geographic_plane(49.06, 1.0, north_slope_degrees=3.0)
    elevation[10:12, 10:12] = np.nan

    # Act
    slope, _ = slope_aspect_degrees(elevation, *spacing)

    # Assert
    finite = slope[np.isfinite(slope)]
    assert np.isnan(slope[10, 10])
    assert float(np.max(finite)) == pytest.approx(3.0, abs=0.05)


def _write_dem(path: Path, latitude: float, elevation: np.ndarray, res_x_arcsec: float) -> None:
    import rasterio
    from rasterio.transform import from_origin

    transform = from_origin(
        -122.2, latitude + elevation.shape[0] * ARC_SECOND / 2, res_x_arcsec * ARC_SECOND, ARC_SECOND
    )
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=elevation.shape[1],
        height=elevation.shape[0],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as dataset:
        dataset.write(elevation.astype("float32"), 1)


def _patch_dem_catalog(monkeypatch: pytest.MonkeyPatch, href: Path) -> None:
    import planetary_computer

    import geoint.terrain_tools as terrain_tools

    item = SimpleNamespace(
        id="Copernicus_DSM_COG_10_N49_00_W123_00_DEM",
        assets={"data": SimpleNamespace(href=str(href))},
    )
    catalog = SimpleNamespace(
        search=lambda **_kwargs: SimpleNamespace(items=lambda: iter([item]))
    )
    monkeypatch.setattr(terrain_tools, "_get_catalog", lambda: catalog)
    monkeypatch.setattr(planetary_computer, "sign", lambda value: value)


def test_given_sumas_dem_when_slope_tool_runs_then_reports_metric_slope_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Arrange
    import geoint.terrain_tools as terrain_tools

    elevation, _ = _geographic_plane(49.06, 1.0, north_slope_degrees=6.0, size=720)
    dem = tmp_path / "sumas.tif"
    _write_dem(dem, 49.06, elevation, 1.0)
    _patch_dem_catalog(monkeypatch, dem)

    # Act
    result = json.loads(terrain_tools.get_slope_analysis(49.06, -122.09, 2.0))

    # Assert
    assert result["slope_mean_degrees"] == pytest.approx(6.0, abs=0.1)
    assert result["moderate_slope_percent"] == pytest.approx(100.0, abs=0.1)
    assert result["source_item_ids"] == ["Copernicus_DSM_COG_10_N49_00_W123_00_DEM"]
    assert result["coverage_percent"] == 100.0
    assert result["cell_spacing_meters"] == {"north_south": 30.9, "east_west": 20.3}
    assert len(result["analysis_bbox"]) == 4
    assert result["valid_pixel_count"] > 0


def test_given_gentle_dem_when_aspect_tool_runs_then_flat_share_is_not_degree_scaled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Arrange
    import geoint.terrain_tools as terrain_tools

    elevation, _ = _geographic_plane(49.06, 1.0, north_slope_degrees=2.0, size=720)
    dem = tmp_path / "gentle.tif"
    _write_dem(dem, 49.06, elevation, 1.0)
    _patch_dem_catalog(monkeypatch, dem)

    # Act
    result = json.loads(terrain_tools.get_aspect_analysis(49.06, -122.09, 2.0))

    # Assert
    assert result["flat_terrain_percent"] == pytest.approx(100.0, abs=0.1)
    assert result["dominant_direction"] == "S"


def test_given_geographic_spacing_when_mobility_classifies_then_east_west_cells_are_narrow() -> None:
    # Arrange
    from geoint.mobility_tools import _analyze_elevation_pixels

    elevation, spacing = _geographic_plane(49.06, 1.0, east_slope_degrees=20.0)

    # Act
    measured = _analyze_elevation_pixels(elevation, spacing)
    assumed = _analyze_elevation_pixels(elevation)

    # Assert
    assert measured["metrics"]["avg"] == pytest.approx(20.0, abs=0.1)
    assert assumed["metrics"]["avg"] < 14.0
