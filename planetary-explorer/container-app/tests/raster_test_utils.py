"""Write small GeoTIFF tiles for raster mosaic and terrain tool tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def write_tile(
    path: Path,
    *,
    west: float,
    north: float,
    width: int,
    height: int,
    res_x: float,
    res_y: float,
    values,
    nodata=None,
    crs: str = "EPSG:4326",
    dtype: str = "float32",
) -> str:
    """Write ``values(lon, lat)`` sampled at cell centres; return the file path."""
    import rasterio
    from rasterio.transform import from_origin

    transform = from_origin(west, north, res_x, res_y)
    rows, cols = np.mgrid[0:height, 0:width]
    lon = west + (cols + 0.5) * res_x
    lat = north - (rows + 0.5) * res_y
    data = np.asarray(values(lon, lat), dtype=dtype)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype=dtype,
        crs=crs,
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(data, 1)
    return str(path)
