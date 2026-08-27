"""Deterministic spectral-index sampling from Public Planetary Computer COGs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
import logging
import math
import re
from typing import Any


logger = logging.getLogger(__name__)

_PUBLIC_STAC_SEARCH_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
_EXACT_DATE_SEARCH_RADIUS_DAYS = 14
_MAX_CANDIDATES_TO_SAMPLE = 12
_MAX_OUTPUT_DIMENSION = 1024
_LOW_CLOUD_THRESHOLD = 30.0
_VALID_SENTINEL_2_SCL_CLASSES = frozenset({2, 4, 5, 6, 7})


class RasterSamplingError(RuntimeError):
    """Raised when no suitable scene or numeric raster pixels can be retrieved."""


@dataclass(frozen=True)
class TemporalWindow:
    """Normalized STAC search interval for a requested epoch."""

    requested: str
    start: date
    end: date
    target: datetime

    @property
    def stac_datetime(self) -> str:
        """Return the interval in STAC API syntax."""
        return f"{self.start.isoformat()}/{self.end.isoformat()}"


@dataclass(frozen=True)
class SpectralIndexSample:
    """Numeric summary and provenance for one sampled scene."""

    metric: str
    value: float
    mean: float
    median: float
    minimum: float
    maximum: float
    standard_deviation: float
    valid_pixel_count: int
    total_pixel_count: int
    valid_pixel_fraction: float
    requested_epoch: str
    search_window: str
    acquisition_datetime: str
    item_id: str
    collection: str
    cloud_cover: float | None
    nir_asset: str
    swir_asset: str
    mask_asset: str | None
    item_url: str

    def to_dict(self) -> dict[str, Any]:
        """Convert the sample to a JSON-compatible dictionary."""
        return asdict(self)


def normalize_temporal_window(
    when: str,
    *,
    today: date | None = None,
) -> TemporalWindow:
    """Normalize an ISO day, month, or year into a bounded STAC interval."""
    raw = when.strip()
    if not raw:
        raise ValueError("The requested epoch cannot be empty.")

    current_date = today or datetime.now(UTC).date()
    if re.fullmatch(r"\d{4}", raw):
        year = int(raw)
        start = date(year, 1, 1)
        end = date(year, 12, 31)
        target_date = date(year, 7, 2)
    elif re.fullmatch(r"\d{4}-\d{2}", raw):
        start = date.fromisoformat(f"{raw}-01")
        if start.month == 12:
            following_month = date(start.year + 1, 1, 1)
        else:
            following_month = date(start.year, start.month + 1, 1)
        end = following_month - timedelta(days=1)
        target_date = start + (end - start) / 2
    else:
        try:
            target_date = datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                target_date = date.fromisoformat(raw)
            except ValueError as exc:
                raise ValueError(
                    f"Unsupported epoch '{when}'. Use YYYY, YYYY-MM, or an ISO date."
                ) from exc
        start = target_date - timedelta(days=_EXACT_DATE_SEARCH_RADIUS_DAYS)
        end = target_date + timedelta(days=_EXACT_DATE_SEARCH_RADIUS_DAYS)

    end = min(end, current_date)
    if start > end:
        raise RasterSamplingError(
            f"Epoch {when} is later than the latest possible observation date "
            f"({current_date.isoformat()})."
        )

    return TemporalWindow(
        requested=raw,
        start=start,
        end=end,
        target=datetime.combine(target_date, datetime.min.time(), tzinfo=UTC),
    )


def _parse_item_datetime(item: dict[str, Any]) -> datetime | None:
    properties = item.get("properties") or {}
    raw = properties.get("datetime") or properties.get("start_datetime")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _contains_point(item: dict[str, Any], latitude: float, longitude: float) -> bool:
    bbox = item.get("bbox") or []
    return (
        len(bbox) >= 4
        and float(bbox[0]) <= longitude <= float(bbox[2])
        and float(bbox[1]) <= latitude <= float(bbox[3])
    )


def _cloud_cover(item: dict[str, Any]) -> float:
    """Return item-level cloud cover, sorting missing values last."""
    raw = (item.get("properties") or {}).get("eo:cloud_cover")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 100.0


def rank_stac_candidates(
    items: list[dict[str, Any]],
    *,
    target: datetime,
    latitude: float,
    longitude: float,
) -> list[dict[str, Any]]:
    """Rank scenes by spatial coverage, distance from epoch, then cloud cover."""
    def score(item: dict[str, Any]) -> tuple[float, float, float, str]:
        acquired = _parse_item_datetime(item)
        distance = abs((acquired - target).total_seconds()) if acquired else math.inf
        cloud_cover = _cloud_cover(item)
        return (
            0.0 if _contains_point(item, latitude, longitude) else 1.0,
            distance,
            cloud_cover,
            str(item.get("id") or ""),
        )

    return sorted(items, key=score)


def _search_stac_items(
    collection: str,
    bbox: tuple[float, float, float, float],
    window: TemporalWindow,
) -> list[dict[str, Any]]:
    import httpx

    body = {
        "collections": [collection],
        "bbox": list(bbox),
        "datetime": window.stac_datetime,
        "limit": 100,
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(_PUBLIC_STAC_SEARCH_URL, json=body)
        response.raise_for_status()
    features = response.json().get("features") or []
    return [feature for feature in features if isinstance(feature, dict)]


def _window_for_bounds(src: Any, bbox: tuple[float, float, float, float]) -> Any:
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds

    if src.crs and str(src.crs) != "EPSG:4326":
        native_bounds = transform_bounds("EPSG:4326", src.crs, *bbox, densify_pts=21)
    else:
        native_bounds = bbox

    left = max(float(native_bounds[0]), float(src.bounds.left))
    bottom = max(float(native_bounds[1]), float(src.bounds.bottom))
    right = min(float(native_bounds[2]), float(src.bounds.right))
    top = min(float(native_bounds[3]), float(src.bounds.top))
    if left >= right or bottom >= top:
        raise RasterSamplingError("The selected scene does not overlap the requested extent.")

    requested_window = from_bounds(left, bottom, right, top, src.transform)
    full_window = Window(0, 0, src.width, src.height)
    return requested_window.intersection(full_window).round_offsets().round_lengths()


def _output_shape(window: Any) -> tuple[int, int]:
    height = max(1, int(window.height))
    width = max(1, int(window.width))
    scale = min(1.0, _MAX_OUTPUT_DIMENSION / max(height, width))
    return max(1, round(height * scale)), max(1, round(width * scale))


def _sample_sentinel_2_nbr(
    item: dict[str, Any],
    *,
    bbox: tuple[float, float, float, float],
    window: TemporalWindow,
) -> SpectralIndexSample:
    import numpy as np
    import planetary_computer as planetary_computer
    import rasterio
    from rasterio.enums import Resampling

    signed_item = planetary_computer.sign(item)
    assets = signed_item.get("assets") or {}
    nir_asset = (
        "B08"
        if (assets.get("B08") or {}).get("href")
        else "B8A"
    )
    swir_asset = "B12"
    mask_asset = "SCL" if "SCL" in assets else None
    missing = [key for key in (nir_asset, swir_asset) if not (assets.get(key) or {}).get("href")]
    if missing:
        raise RasterSamplingError(
            f"Scene {item.get('id', 'unknown')} is missing required NBR assets: {', '.join(missing)}."
        )

    environment = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF,.tiff,.TIFF",
        "GDAL_HTTP_TIMEOUT": "30",
        "GDAL_HTTP_MAX_RETRY": "3",
    }
    with rasterio.Env(**environment):
        with rasterio.open(assets[nir_asset]["href"]) as nir_src, rasterio.open(
            assets[swir_asset]["href"]
        ) as swir_src:
            raster_window = _window_for_bounds(nir_src, bbox)
            output_shape = _output_shape(raster_window)
            nir = nir_src.read(
                1,
                window=raster_window,
                out_shape=output_shape,
                masked=True,
                resampling=Resampling.bilinear,
            ).astype("float32")
            swir = swir_src.read(
                1,
                window=raster_window,
                out_shape=output_shape,
                masked=True,
                resampling=Resampling.bilinear,
            ).astype("float32")

            nir_values = np.asarray(nir.filled(np.nan), dtype="float32")
            swir_values = np.asarray(swir.filled(np.nan), dtype="float32")
            nir_values = nir_values * float(nir_src.scales[0]) + float(nir_src.offsets[0])
            swir_values = swir_values * float(swir_src.scales[0]) + float(swir_src.offsets[0])
            valid = np.isfinite(nir_values) & np.isfinite(swir_values)

            if mask_asset and (assets.get(mask_asset) or {}).get("href"):
                with rasterio.open(assets[mask_asset]["href"]) as mask_src:
                    mask_window = _window_for_bounds(mask_src, bbox)
                    scene_classification = mask_src.read(
                        1,
                        window=mask_window,
                        out_shape=output_shape,
                        masked=True,
                        resampling=Resampling.nearest,
                    )
                valid &= np.isin(
                    np.asarray(scene_classification.filled(0)),
                    tuple(_VALID_SENTINEL_2_SCL_CLASSES),
                )

    denominator = nir_values + swir_values
    valid &= denominator != 0
    nbr = np.full(nir_values.shape, np.nan, dtype="float32")
    nbr[valid] = (nir_values[valid] - swir_values[valid]) / denominator[valid]
    values = nbr[np.isfinite(nbr)]
    if values.size == 0:
        raise RasterSamplingError(
            f"Scene {item.get('id', 'unknown')} has no valid cloud-free NBR pixels in the requested extent."
        )

    properties = item.get("properties") or {}
    acquisition = _parse_item_datetime(item)
    item_id = str(item.get("id") or "unknown")
    collection = str(item.get("collection") or "sentinel-2-l2a")
    cloud_raw = properties.get("eo:cloud_cover")
    try:
        cloud_cover = float(cloud_raw)
    except (TypeError, ValueError):
        cloud_cover = None

    return SpectralIndexSample(
        metric="nbr",
        value=float(np.mean(values)),
        mean=float(np.mean(values)),
        median=float(np.median(values)),
        minimum=float(np.min(values)),
        maximum=float(np.max(values)),
        standard_deviation=float(np.std(values)),
        valid_pixel_count=int(values.size),
        total_pixel_count=int(nbr.size),
        valid_pixel_fraction=float(values.size / nbr.size),
        requested_epoch=window.requested,
        search_window=window.stac_datetime,
        acquisition_datetime=acquisition.isoformat() if acquisition else "",
        item_id=item_id,
        collection=collection,
        cloud_cover=cloud_cover,
        nir_asset=nir_asset,
        swir_asset=swir_asset,
        mask_asset=mask_asset,
        item_url=(
            f"https://planetarycomputer.microsoft.com/api/stac/v1/collections/"
            f"{collection}/items/{item_id}"
        ),
    )


def sample_temporal_nbr(
    collection: str,
    when: str,
    *,
    bbox: tuple[float, float, float, float],
    today: date | None = None,
) -> SpectralIndexSample:
    """Retrieve and summarize NBR for the best usable scene near an epoch."""
    if collection != "sentinel-2-l2a":
        raise ValueError(
            "Deterministic NBR sampling currently supports the sentinel-2-l2a collection."
        )

    west, south, east, north = bbox
    if west >= east or south >= north:
        raise ValueError("The raster sampling extent must be a valid WGS84 bbox.")

    window = normalize_temporal_window(when, today=today)
    items = _search_stac_items(collection, bbox, window)
    if not items:
        raise RasterSamplingError(
            f"No {collection} scenes intersect the extent during {window.stac_datetime}."
        )

    latitude = (south + north) / 2
    longitude = (west + east) / 2
    low_cloud_items = [item for item in items if _cloud_cover(item) < _LOW_CLOUD_THRESHOLD]
    candidates = rank_stac_candidates(
        low_cloud_items or items,
        target=window.target,
        latitude=latitude,
        longitude=longitude,
    )
    failures: list[str] = []
    for item in candidates[:_MAX_CANDIDATES_TO_SAMPLE]:
        try:
            return _sample_sentinel_2_nbr(item, bbox=bbox, window=window)
        except RasterSamplingError as exc:
            failures.append(str(exc))
        except Exception as exc:  # noqa: BLE001
            item_id = str(item.get("id") or "unknown")
            failures.append(f"Scene {item_id} could not be read: {type(exc).__name__}: {exc}")
            logger.warning("NBR sampling failed for %s", item_id, exc_info=True)

    detail = "; ".join(failures[:3])
    raise RasterSamplingError(
        f"Found {len(items)} {collection} scenes near {when}, but none returned valid NBR pixels. "
        f"{detail}"
    )