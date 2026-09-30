"""Read a bounding box across tiled rasters on one grid.

Planetary Computer publishes Copernicus DEM GLO-30 in 1-degree tiles, ESA
WorldCover in 3-degree tiles, and JRC Global Surface Water in 10-degree
tiles. Even a 5 km analysis radius crosses a tile edge at many Canadian
locations (Brandon, Medicine Hat, and Whitehorse, for example), so reading
only the first STAC match silently analyses part of the requested area.

``read_bbox_mosaic`` combines every intersecting tile on the finest source
grid, marks missing coverage as NaN, and reports the covered share of the
requested box.
"""

from __future__ import annotations

import math
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

DEFAULT_MAX_PIXELS = 9_000_000


@dataclass(frozen=True)
class MosaicWindow:
    """Float raster for a bounding box; NaN marks nodata or missing tiles."""

    data: np.ndarray
    transform: Any
    resolution: tuple[float, float]
    decimation: int
    source_count: int
    geographic: bool

    @property
    def valid_mask(self) -> np.ndarray:
        return np.isfinite(self.data)

    @property
    def coverage_percent(self) -> float:
        if self.data.size == 0:
            return 0.0
        return float(np.count_nonzero(self.valid_mask) / self.data.size * 100.0)

    def pixel_index(self, x: float, y: float) -> tuple[int, int]:
        """Return the ``(row, column)`` containing ``x, y``, clamped to the grid."""
        column, row = ~self.transform * (x, y)
        return (
            min(max(int(math.floor(row)), 0), self.data.shape[0] - 1),
            min(max(int(math.floor(column)), 0), self.data.shape[1] - 1),
        )


def _snap_bounds(
    bbox: Sequence[float],
    origin: tuple[float, float],
    resolution: tuple[float, float],
) -> tuple[float, float, float, float]:
    """Expand ``bbox`` outward to whole cells of the lattice through ``origin``."""
    origin_x, origin_y = origin
    res_x, res_y = resolution
    tolerance = 1e-6
    west = origin_x + math.floor((bbox[0] - origin_x) / res_x + tolerance) * res_x
    east = origin_x + math.ceil((bbox[2] - origin_x) / res_x - tolerance) * res_x
    north = origin_y - math.floor((origin_y - bbox[3]) / res_y + tolerance) * res_y
    south = origin_y - math.ceil((origin_y - bbox[1]) / res_y - tolerance) * res_y
    return west, south, east, north


def read_bbox_mosaic(
    sources: Sequence[str],
    bbox: Sequence[float],
    *,
    categorical: bool = False,
    band: int = 1,
    max_pixels: int = DEFAULT_MAX_PIXELS,
) -> MosaicWindow:
    """Read ``bbox`` from all ``sources`` onto the finest shared grid.

    Sources must share a CRS and ``bbox`` must be in that CRS. Cells outside
    every source, or equal to a source's declared nodata, are NaN. Continuous
    data uses bilinear resampling only where a coarser tile is upsampled or
    the output is decimated; aligned tiles are copied cell for cell.
    Categorical data always uses nearest-neighbour resampling. When the box
    would exceed ``max_pixels`` cells, the grid is coarsened by a whole-number
    factor and reported through ``decimation``.
    """
    if not sources:
        raise ValueError("At least one raster source is required")

    import rasterio
    from rasterio.enums import Resampling
    from rasterio.merge import merge

    with ExitStack() as stack:
        datasets = [stack.enter_context(rasterio.open(source)) for source in sources]
        crs = datasets[0].crs
        if any(dataset.crs != crs for dataset in datasets[1:]):
            raise ValueError("Raster sources use different coordinate reference systems")

        finest = min(datasets, key=lambda dataset: abs(dataset.res[0] * dataset.res[1]))
        base_resolution = (abs(finest.res[0]), abs(finest.res[1]))
        origin = (finest.transform.c, finest.transform.f)
        west, south, east, north = _snap_bounds(bbox, origin, base_resolution)
        columns = max(1, round((east - west) / base_resolution[0]))
        rows = max(1, round((north - south) / base_resolution[1]))
        decimation = 1
        if max_pixels > 0:
            decimation = max(1, math.floor(math.sqrt(columns * rows / max_pixels)))
            while math.ceil(columns / decimation) * math.ceil(rows / decimation) > max_pixels:
                decimation += 1
        resolution = (base_resolution[0] * decimation, base_resolution[1] * decimation)
        if decimation > 1:
            west, south, east, north = _snap_bounds(bbox, origin, resolution)
        if east - west < resolution[0] or north - south < resolution[1]:
            raise ValueError("Bounding box is smaller than one raster cell")

        mosaic, transform = merge(
            datasets,
            bounds=(west, south, east, north),
            res=resolution,
            indexes=[band],
            nodata=np.nan,
            dtype="float64",
            resampling=Resampling.nearest if categorical else Resampling.bilinear,
        )

    return MosaicWindow(
        data=mosaic[0],
        transform=transform,
        resolution=resolution,
        decimation=decimation,
        source_count=len(datasets),
        geographic=bool(crs is not None and crs.is_geographic),
    )
