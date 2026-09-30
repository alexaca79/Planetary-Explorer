"""Bounding-box reads across tiled rasters (Copernicus DEM, JRC, WorldCover)."""

from __future__ import annotations

import math

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")

from geoint.raster_mosaic import read_bbox_mosaic  # noqa: E402
from raster_test_utils import write_tile  # noqa: E402


def plane(lon, lat):
    return 100.0 + 1000.0 * (lon + 100.0) + 500.0 * (lat - 49.0)


def rough(lon, lat):
    """High-frequency surface; any resampling shift would change cell values."""
    return 200.0 + 50.0 * np.sin(lon * 977.0) * np.cos(lat * 613.0)


def test_mosaic_covers_bbox_across_a_tile_edge_without_resampling(tmp_path):
    # Copernicus-style tiles: pixel-is-point origins offset by half a cell.
    res = 0.001
    half = res / 2
    west_tile = write_tile(
        tmp_path / "west.tif", west=-100.2 - half, north=49.2 + half,
        width=200, height=200, res_x=res, res_y=res, values=rough,
    )
    east_tile = write_tile(
        tmp_path / "east.tif", west=-100.0 - half, north=49.2 + half,
        width=200, height=200, res_x=res, res_y=res, values=rough,
    )
    bbox = [-100.05, 49.05, -99.95, 49.15]

    window = read_bbox_mosaic([west_tile, east_tile], bbox)

    assert window.coverage_percent == pytest.approx(100.0)
    assert window.decimation == 1
    assert window.source_count == 2
    assert window.geographic is True
    rows, cols = np.mgrid[0:window.data.shape[0], 0:window.data.shape[1]]
    lon = window.transform.c + (cols + 0.5) * window.resolution[0]
    lat = window.transform.f - (rows + 0.5) * window.resolution[1]
    np.testing.assert_allclose(window.data, rough(lon, lat).astype("float32"), atol=1e-3)
    assert window.transform.c <= bbox[0] and window.transform.f >= bbox[3]


def test_single_tile_reports_partial_coverage(tmp_path):
    res = 0.001
    west_tile = write_tile(
        tmp_path / "west.tif", west=-100.2, north=49.2,
        width=200, height=200, res_x=res, res_y=res, values=plane,
    )
    bbox = [-100.05, 49.05, -99.95, 49.15]

    window = read_bbox_mosaic([west_tile], bbox)

    assert window.coverage_percent == pytest.approx(50.0, abs=1.0)
    assert np.isnan(window.data[:, -1]).all()


def test_coarser_neighbour_is_upsampled_to_the_finest_grid(tmp_path):
    # Copernicus longitude spacing widens from 1" to 1.5" at 50 N.
    south = write_tile(
        tmp_path / "south.tif", west=-111.0, north=50.0,
        width=1000, height=100, res_x=0.001, res_y=0.001, values=plane,
    )
    north = write_tile(
        tmp_path / "north.tif", west=-111.0, north=50.1,
        width=667, height=100, res_x=0.0015, res_y=0.001, values=plane,
    )
    bbox = [-110.75, 49.96, -110.6, 50.04]

    window = read_bbox_mosaic([north, south], bbox)

    assert window.resolution == pytest.approx((0.001, 0.001))
    assert window.coverage_percent == pytest.approx(100.0)
    rows, cols = np.mgrid[0:window.data.shape[0], 0:window.data.shape[1]]
    lon = window.transform.c + (cols + 0.5) * window.resolution[0]
    lat = window.transform.f - (rows + 0.5) * window.resolution[1]
    np.testing.assert_allclose(window.data, plane(lon, lat), atol=1.0)


def test_declared_nodata_and_missing_tiles_become_nan(tmp_path):
    def values(lon, lat):
        grid = np.full(lon.shape, 40.0)
        grid[:, :10] = 0
        return grid

    tile = write_tile(
        tmp_path / "landcover.tif", west=-124.0, north=49.4,
        width=100, height=100, res_x=0.001, res_y=0.001,
        values=values, nodata=0, dtype="uint8",
    )

    window = read_bbox_mosaic([tile], [-124.0, 49.3, -123.9, 49.4], categorical=True)

    assert np.isnan(window.data[:, :10]).all()
    assert np.all(window.data[:, 10:] == 40)
    assert window.coverage_percent == pytest.approx(90.0)


def test_large_boxes_are_decimated_by_a_whole_factor(tmp_path):
    tile = write_tile(
        tmp_path / "dem.tif", west=-100.2, north=49.2,
        width=200, height=200, res_x=0.001, res_y=0.001, values=plane,
    )

    window = read_bbox_mosaic([tile], [-100.2, 49.0, -100.0, 49.2], max_pixels=10_000)

    assert window.decimation == 2
    assert window.resolution == pytest.approx((0.002, 0.002))
    assert window.data.shape == (100, 100)


def test_pixel_index_locates_the_site_not_the_array_centre(tmp_path):
    tile = write_tile(
        tmp_path / "dem.tif", west=-100.2, north=49.2,
        width=200, height=200, res_x=0.001, res_y=0.001, values=plane,
    )
    window = read_bbox_mosaic([tile], [-100.2, 49.0, -100.0, 49.2])

    assert window.pixel_index(-100.1995, 49.1995) == (0, 0)
    assert window.pixel_index(-100.0005, 49.0005) == (199, 199)
    assert window.pixel_index(-150.0, 10.0) == (199, 0)


def test_sources_in_different_crs_are_rejected(tmp_path):
    geographic = write_tile(
        tmp_path / "a.tif", west=-100.2, north=49.2,
        width=10, height=10, res_x=0.001, res_y=0.001, values=plane,
    )
    projected = write_tile(
        tmp_path / "b.tif", west=500000.0, north=5450000.0,
        width=10, height=10, res_x=30.0, res_y=30.0,
        values=lambda lon, lat: np.zeros(lon.shape), crs="EPSG:32610",
    )

    with pytest.raises(ValueError, match="coordinate reference"):
        read_bbox_mosaic([geographic, projected], [-100.2, 49.19, -100.19, 49.2])


def test_empty_source_list_is_rejected():
    with pytest.raises(ValueError):
        read_bbox_mosaic([], [0, 0, 1, 1])


def test_box_smaller_than_one_cell_is_rejected(tmp_path):
    tile = write_tile(
        tmp_path / "dem.tif", west=-100.2, north=49.2,
        width=10, height=10, res_x=0.01, res_y=0.01, values=plane,
    )
    with pytest.raises(ValueError, match="smaller than one raster cell"):
        read_bbox_mosaic([tile], [-100.15, 49.15, -100.15, 49.15])
    assert math.isfinite(read_bbox_mosaic([tile], [-100.151, 49.149, -100.149, 49.151]).data[0, 0])
