"""Mobility sectors across Copernicus DEM tile edges, and route error wording."""

from __future__ import annotations

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")

from raster_test_utils import write_tile  # noqa: E402

RES = 0.005


def _dem_tiles(tmp_path, *, include_east: bool = True) -> list[str]:
    """Two DEM tiles meeting at 115 W; elevation rises 1 m per 10 m eastward."""

    def surface(lon, lat):
        return 1500.0 + (lon + 115.0) * 7000.0 + (lat - 50.7) * 100.0

    tiles = [
        write_tile(tmp_path / "west.tif", west=-115.2, north=50.8, width=40, height=40,
                   res_x=RES, res_y=RES, values=surface),
    ]
    if include_east:
        tiles.append(
            write_tile(tmp_path / "east.tif", west=-115.0, north=50.8, width=40, height=40,
                       res_x=RES, res_y=RES, values=surface),
        )
    return tiles


class _Asset:
    def __init__(self, href: str) -> None:
        self.href = href


class _Item:
    def __init__(self, href: str, bbox: list[float]) -> None:
        self.bbox = bbox
        self.assets = {"data": _Asset(href)}


class _RouteResponse:
    def __init__(self, status_code: int, body=None) -> None:
        self.status_code = status_code
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("not JSON")
        return self._body


@pytest.fixture
def tools_module(monkeypatch):
    import geoint.mobility_tools as module

    monkeypatch.setattr(module.planetary_computer, "sign_url", lambda url: url)
    return module


def test_given_sector_across_tile_edge_when_reading_dem_then_both_tiles_fill_it(
    tmp_path, tools_module
) -> None:
    # Arrange: the north sector of a pin on 115 W straddles both tiles.
    sector = tools_module._calculate_directional_bbox(50.7, -115.0, "N")

    # Act
    data, spacing = tools_module._read_dem_mosaic_with_spacing_sync(
        _dem_tiles(tmp_path), sector, 50.7
    )

    # Assert
    assert data.shape[0] >= 2 and data.shape[1] >= 2
    assert np.isfinite(data).all()
    assert spacing[0] == pytest.approx(RES * 111_229, rel=0.01)
    assert spacing[1] == pytest.approx(RES * 70_600, rel=0.01)


def test_given_sector_beyond_available_tile_when_reading_dem_then_gap_is_nan_not_error(
    tmp_path, tools_module
) -> None:
    # Arrange: only the western tile exists for a sector crossing 115 W.
    sector = tools_module._calculate_directional_bbox(50.7, -115.0, "N")

    # Act
    data, _spacing = tools_module._read_dem_mosaic_with_spacing_sync(
        _dem_tiles(tmp_path, include_east=False), sector, 50.7
    )
    result = tools_module._analyze_elevation_pixels(data, _spacing)

    # Assert
    assert np.isnan(data).any() and np.isfinite(data).any()
    assert result["confidence"] == "high"


def test_given_pin_on_tile_edge_when_analyzing_direction_then_elevation_is_measured(
    tmp_path, tools_module
) -> None:
    # Arrange: each sector of a pin on 115 W must read the tile(s) under it.
    west, east = _dem_tiles(tmp_path)
    terrain_data = {
        "elevation_profile": {
            "items": [
                _Item(west, [-115.2, 50.6, -115.0, 50.8]),
                _Item(east, [-115.0, 50.6, -114.8, 50.8]),
            ]
        }
    }

    # Act
    results = {
        cardinal: tools_module._analyze_single_direction_sync(cardinal, 50.7, -115.0, terrain_data, cardinal)
        for cardinal in ("N", "S", "E", "W")
    }

    # Assert: 7000 m per degree of longitude is a 1-in-10 grade, about 5.7 degrees.
    for cardinal, result in results.items():
        assert "Copernicus DEM" in result["data_sources_used"], cardinal
        assert result["metrics"]["elevation"]["avg"] == pytest.approx(5.7, abs=0.15), cardinal


def test_given_dem_items_when_selecting_for_endpoint_then_every_tile_under_box_is_kept(
    tools_module,
) -> None:
    # Arrange
    west = _Item("west", [-116.0, 50.0, -115.0, 51.0])
    east = _Item("east", [-115.0, 50.0, -114.0, 51.0])
    distant = _Item("distant", [-10.0, -10.0, -9.0, -9.0])
    box = [-115.1, 50.63, -114.94, 50.77]

    # Act
    dem = tools_module._endpoint_items("cop-dem-glo-30", [west, east, distant], box, 50.7, -115.02)
    water = tools_module._endpoint_items("jrc-gsw", [west, east, distant], box, 50.7, -115.02)

    # Assert
    assert dem == [west, east]
    assert water == [west]


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            _RouteResponse(400, {"error": {"code": "400 BadRequest", "message": "Engine error while executing route request: MAP_MATCHING_FAILURE: Origin (50.7, -115)"}}),
            "No drivable road near one of the points",
        ),
        (
            _RouteResponse(400, {"error": {"code": "400 BadRequest", "message": "NO_ROUTE_FOUND"}}),
            "No road route found between points",
        ),
        (_RouteResponse(500), "API error 500"),
        (_RouteResponse(400, {"error": {"message": "Invalid query"}}), "API error 400"),
    ],
)
def test_given_route_error_when_explaining_then_backcountry_is_not_reported_as_fault(
    tools_module, response, expected
) -> None:
    # Act and assert
    assert tools_module._route_error_reason(response) == expected
