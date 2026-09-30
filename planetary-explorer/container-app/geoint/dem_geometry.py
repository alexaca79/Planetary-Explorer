"""Metric slope and aspect for elevation grids in geographic or projected CRSs.

Copernicus DEM GLO-30 is stored in EPSG:4326 with 1 arc-second rows and
longitude spacing that widens with latitude (1.5" from 50 N, 2" from 60 N,
3" from 70 N, 5" from 80 N). Treating both axes as one cell size overstates
north-south gradients by up to about 50 percent across southern Canada.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def pixel_spacing_meters(
    res_x: float,
    res_y: float,
    latitude: float,
    *,
    geographic: bool,
) -> tuple[float, float]:
    """Return ``(row_spacing_m, column_spacing_m)`` for one raster cell."""
    if not geographic:
        return abs(float(res_y)), abs(float(res_x))
    phi = math.radians(latitude)
    meters_per_degree_latitude = (
        111132.92 - 559.82 * math.cos(2 * phi) + 1.175 * math.cos(4 * phi)
    )
    meters_per_degree_longitude = 111412.84 * math.cos(phi) - 93.5 * math.cos(3 * phi)
    return (
        abs(float(res_y)) * meters_per_degree_latitude,
        abs(float(res_x)) * max(meters_per_degree_longitude, 1e-6),
    )


def dataset_spacing_meters(dataset: Any, latitude: float) -> tuple[float, float]:
    """Return metric cell spacing for an open rasterio dataset."""
    crs = getattr(dataset, "crs", None)
    geographic = bool(getattr(crs, "is_geographic", False)) if crs else False
    res_x, res_y = dataset.res
    return pixel_spacing_meters(res_x, res_y, latitude, geographic=geographic)


def slope_aspect_degrees(
    elevation: np.ndarray,
    row_spacing_m: float,
    column_spacing_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return slope (0-90 degrees) and downslope aspect (0-360, 0 = north).

    Rows are assumed to increase southward, as in north-up rasters. Cells
    that are NaN, or adjacent to NaN, yield NaN slope and aspect.
    """
    surface = np.asarray(elevation, dtype=float)
    dz_row, dz_column = np.gradient(surface, row_spacing_m, column_spacing_m)
    slope = np.degrees(np.arctan(np.hypot(dz_row, dz_column)))
    aspect = np.degrees(np.arctan2(-dz_column, dz_row)) % 360.0
    return slope, aspect
