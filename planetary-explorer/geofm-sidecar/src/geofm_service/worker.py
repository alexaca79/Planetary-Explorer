"""Queue-driven PlanAura worker that produces bounded geospatial evidence."""

from __future__ import annotations

import hashlib
import heapq
import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from uuid import UUID, uuid4

import numpy as np
import rasterio
from affine import Affine
from pyproj import Geod
from rasterio.features import geometry_mask, shapes
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling, transform_geom
from shapely.geometry import mapping, shape

from .contracts import ClassifyAoiRequest, RunArtifact, RunRecord, RunStatus
from .jobs import (
    BlobRunRepository,
    NoopDispatcher,
    PreprocessingRecipe,
    RunConflict,
    RunNotFound,
    RunRepositoryError,
    RunService,
)
from .model import PlanAuraAdapter, normalize_epochs, normalize_frames
from .policy import ModelDescriptor, get_class_scheme
from .stac import StacItemSummary, get_catalog

logger = logging.getLogger(__name__)
GEOD = Geod(ellps="WGS84")
UTC = timezone.utc
ALLOWED_ASSET_HOST_SUFFIXES = (".blob.core.windows.net",)
SENTINEL2_VALID_SCL_CLASSES = (4, 5, 6, 7, 11)
SENTINEL3_INVALID_FLAG_MASK = np.uint32(0b0000_0000_0000_0000_1000_0011_0000_0011)
KMEANS_MAX_ITERATIONS = 50
OPTICAL_BAND_SEMANTICS = ("BLUE", "GREEN", "RED", "NIR_NARROW", "SWIR_1", "SWIR_2")
CLASSIFICATION_SEED = 20240601
SPECTRAL_INDEX_BANDS = {
    "ndvi": ("NIR_NARROW", "RED"),
    "ndwi": ("GREEN", "NIR_NARROW"),
    "nbr": ("NIR_NARROW", "SWIR_2"),
}
CLASS_NAMING_RULES = {
    "water": lambda ndvi, ndwi, nbr: ndwi,
    "open_water": lambda ndvi, ndwi, nbr: ndwi,
    "water_regime": lambda ndvi, ndwi, nbr: ndwi,
    "dense_vegetation": lambda ndvi, ndwi, nbr: ndvi,
    "rough_vegetated": lambda ndvi, ndwi, nbr: ndvi,
    "volume_scattering_forest": lambda ndvi, ndwi, nbr: ndvi,
    "vegetated_land_regime": lambda ndvi, ndwi, nbr: ndvi,
    "sparse_vegetation": lambda ndvi, ndwi, nbr: 0.35 - abs(ndvi - 0.25),
    "bare_or_built": lambda ndvi, ndwi, nbr: -ndvi,
    "smooth_bare": lambda ndvi, ndwi, nbr: -ndvi,
    "bare_land_regime": lambda ndvi, ndwi, nbr: -ndvi,
    "double_bounce_built": lambda ndvi, ndwi, nbr: -ndvi,
    "snow_or_ice": lambda ndvi, ndwi, nbr: ndwi - ndvi,
    "cool_thermal_regime": lambda ndvi, ndwi, nbr: ndwi - ndvi,
    "burned_or_disturbed": lambda ndvi, ndwi, nbr: -nbr,
    "warm_thermal_regime": lambda ndvi, ndwi, nbr: -nbr,
}
WORKER_ID = f"{os.getenv('HOSTNAME', 'geofm-worker')}:{uuid4()}"


class WorkerError(RuntimeError):
    """Raised when a run cannot produce reproducible evidence."""


class RetriableWorkerError(RuntimeError):
    """Raised when an external dependency may recover on redelivery."""


@dataclass(frozen=True)
class PreparedInput:
    """Normalized model tensor and its fixed output grid."""

    values: np.ndarray
    transform: Affine
    crs: object
    aoi_mask: np.ndarray


def prepare_input(
    assets_a: dict[str, str],
    assets_b: dict[str, str],
    geometry: dict,
    recipe: PreprocessingRecipe,
    descriptor: ModelDescriptor,
) -> PreparedInput:
    """Read two epochs into a fixed 512 by 512 grid at native resolution."""
    required = (*recipe.band_assets, recipe.quality_asset)
    for assets in (assets_a, assets_b):
        missing = sorted(set(required) - assets.keys())
        if missing:
            raise WorkerError(f"Signed STAC assets are incomplete: {', '.join(missing)}.")
        for key in required:
            validate_asset_url(assets[key])

    with rasterio.open(assets_a[recipe.band_assets[0]]) as reference:
        if reference.crs is None:
            raise WorkerError("Reference raster has no coordinate reference system.")
        target_transform, aoi_mask = build_fixed_grid(
            reference.crs,
            geometry,
            resolution_m=recipe.target_resolution_m,
            tile_size_pixels=recipe.tile_size_pixels,
        )
        epoch_values = [
            _read_epoch(
                assets,
                reference.crs,
                target_transform,
                recipe,
            )
            for assets in (assets_a, assets_b)
        ]
    raw_values = np.stack(epoch_values, axis=1)[None, ...]
    return PreparedInput(
        values=normalize_epochs(raw_values, descriptor),
        transform=target_transform,
        crs=reference.crs,
        aoi_mask=aoi_mask,
    )


def build_fixed_grid(
    target_crs: object,
    geometry: dict,
    *,
    resolution_m: float,
    tile_size_pixels: int,
) -> tuple[Affine, np.ndarray]:
    """Center a native-resolution square grid on the requested AOI."""
    projected_geometry = transform_geom("EPSG:4326", target_crs, geometry)
    projected_shape = shape(projected_geometry)
    min_x, min_y, max_x, max_y = projected_shape.bounds
    side_m = resolution_m * tile_size_pixels
    if max_x - min_x > side_m or max_y - min_y > side_m:
        raise WorkerError("AOI exceeds the fixed PlanAura context window.")
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    target_transform = Affine(
        resolution_m,
        0,
        center_x - side_m / 2,
        0,
        -resolution_m,
        center_y + side_m / 2,
    )
    mask = geometry_mask(
        [projected_geometry],
        out_shape=(tile_size_pixels, tile_size_pixels),
        transform=target_transform,
        invert=True,
    )
    if not mask.any():
        raise WorkerError("AOI does not intersect the fixed PlanAura grid.")
    return target_transform, mask


def valid_hls_fmask(values: np.ndarray) -> np.ndarray:
    """Return pixels without HLS cloud, adjacency, shadow, snow, or high aerosol."""
    contaminated = (values & np.uint8(0b0001_1111)) != 0
    high_aerosol = ((values >> np.uint8(6)) & np.uint8(0b11)) == 0b11
    return ~(contaminated | high_aerosol)


def vectorize_distance(
    values: np.ndarray,
    *,
    transform_value: Affine,
    crs: object,
    threshold: float,
    max_features: int,
    clip_geometry: dict | None = None,
) -> list[dict]:
    """Convert thresholded model distance into ranked WGS84 polygons."""
    if max_features <= 0:
        return []
    projected_clip = (
        shape(transform_geom("EPSG:4326", crs, clip_geometry, precision=7))
        if clip_geometry is not None
        else None
    )
    valid = np.isfinite(values)
    selected = valid & (values >= threshold)
    selected_values = selected.astype(np.uint8)
    candidates: list[tuple[float, int, dict]] = []
    simplification_tolerance = max(
        abs(transform_value.a),
        abs(transform_value.e),
    ) * 0.5
    for candidate_index, (projected_geometry, value) in enumerate(shapes(
        selected_values,
        mask=selected,
        transform=transform_value,
        connectivity=8,
    )):
        if int(value) != 1:
            continue
        projected_shape = shape(projected_geometry).simplify(
            simplification_tolerance,
            preserve_topology=True,
        )
        if projected_clip is not None:
            projected_shape = projected_shape.intersection(projected_clip)
        if projected_shape.is_empty or projected_shape.area <= 0:
            continue
        candidate = (
            float(projected_shape.area),
            candidate_index,
            mapping(projected_shape),
        )
        if len(candidates) < max_features:
            heapq.heappush(candidates, candidate)
        elif candidate[0] > candidates[0][0]:
            heapq.heapreplace(candidates, candidate)

    features: list[dict] = []
    for _, _, projected_geometry in sorted(candidates, reverse=True):
        region = geometry_mask(
            [projected_geometry],
            out_shape=values.shape,
            transform=transform_value,
            invert=True,
        )
        samples = values[region & selected]
        if samples.size == 0:
            continue
        geometry_wgs84 = transform_geom(crs, "EPSG:4326", projected_geometry, precision=7)
        area_m2, _ = GEOD.geometry_area_perimeter(shape(geometry_wgs84))
        area_km2 = abs(area_m2) / 1_000_000
        if area_km2 <= 0:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": geometry_wgs84,
                "properties": {
                    "area_km2": area_km2,
                    "mean_distance": float(np.mean(samples)),
                    "maximum_distance": float(np.max(samples)),
                    "threshold": threshold,
                },
            }
        )
    ranked = sorted(
        features,
        key=lambda feature: feature["properties"]["area_km2"],
        reverse=True,
    )
    for rank, feature in enumerate(ranked, start=1):
        feature["properties"]["rank"] = rank
    return ranked


def summarize_distance(
    values: np.ndarray,
    *,
    transform_value: Affine,
    threshold: float,
) -> dict:
    """Reduce a distance raster to stable scalar measurements."""
    valid = values[np.isfinite(values)]
    if valid.size == 0:
        raise WorkerError("PlanAura returned no valid values inside the AOI.")
    changed = valid[valid >= threshold]
    pixel_area_m2 = abs(
        transform_value.a * transform_value.e
        - transform_value.b * transform_value.d
    )
    if pixel_area_m2 <= 0:
        raise WorkerError("PlanAura output grid has a non-positive pixel area.")
    return {
        "valid_pixel_count": int(valid.size),
        "changed_pixel_count": int(changed.size),
        "mean_distance": float(np.mean(valid)),
        "maximum_distance": float(np.max(valid)),
        "p95_distance": float(np.percentile(valid, 95)),
        "mean_changed_distance": float(np.mean(changed)) if changed.size else None,
        "changed_area_km2": float(changed.size * pixel_area_m2 / 1_000_000),
        "threshold": threshold,
        "distance_definition": "1 - PlanAura cosine similarity",
    }


@dataclass(frozen=True)
class PreparedScene:
    """Single-date reflectance or backscatter stack on the fixed output grid."""

    values: np.ndarray
    reflectance: np.ndarray
    valid: np.ndarray
    transform: Affine
    crs: object
    aoi_mask: np.ndarray


def quality_mask(strategy: str, values: np.ndarray) -> np.ndarray:
    """Return the per-sensor valid-pixel mask for a quality asset."""
    if strategy == "hls_fmask":
        return valid_hls_fmask(values)
    if strategy == "sentinel2_scl":
        return valid_sentinel2_scl(values)
    if strategy == "sentinel1_rtc_mask":
        return valid_sentinel1_rtc_mask(values)
    if strategy == "sentinel3_quality_flags":
        return valid_sentinel3_flags(values)
    raise WorkerError(f"Unsupported quality mask strategy '{strategy}'.")


def valid_sentinel2_scl(values: np.ndarray) -> np.ndarray:
    """Keep only Sentinel-2 scene classes that carry usable surface reflectance."""
    keep = np.zeros(values.shape, dtype=bool)
    for scene_class in SENTINEL2_VALID_SCL_CLASSES:
        keep |= values == np.uint8(scene_class)
    return keep


def valid_sentinel1_rtc_mask(values: np.ndarray) -> np.ndarray:
    """Keep Sentinel-1 RTC pixels flagged as valid terrain-corrected backscatter."""
    return values == np.uint8(1)


def valid_sentinel3_flags(values: np.ndarray) -> np.ndarray:
    """Drop Sentinel-3 pixels carrying any invalid, cloud, or land/water flag."""
    return (values.astype(np.uint32) & SENTINEL3_INVALID_FLAG_MASK) == 0


def prepare_scene(
    assets: dict[str, str],
    geometry: dict,
    recipe: PreprocessingRecipe,
    descriptor: ModelDescriptor,
) -> PreparedScene:
    """Read one scene into the fixed model grid with its per-sensor quality mask."""
    required = (*recipe.band_assets, recipe.quality_asset)
    missing = sorted(set(required) - assets.keys())
    if missing:
        raise WorkerError(f"Signed STAC assets are incomplete: {', '.join(missing)}.")
    for key in required:
        validate_asset_url(assets[key])

    with rasterio.open(assets[recipe.band_assets[0]]) as reference:
        if reference.crs is None:
            raise WorkerError("Reference raster has no coordinate reference system.")
        target_transform, aoi_mask = build_fixed_grid(
            reference.crs,
            geometry,
            resolution_m=recipe.target_resolution_m,
            tile_size_pixels=recipe.tile_size_pixels,
        )
        reflectance, valid = _read_scene(assets, reference.crs, target_transform, recipe)
        crs = reference.crs
    raw_values = reflectance[None, :, None, :, :]
    return PreparedScene(
        values=normalize_frames(raw_values, descriptor, frames=1),
        reflectance=reflectance,
        valid=valid,
        transform=target_transform,
        crs=crs,
        aoi_mask=aoi_mask,
    )


def _read_scene(
    assets: dict[str, str],
    target_crs: object,
    target_transform: Affine,
    recipe: PreprocessingRecipe,
) -> tuple[np.ndarray, np.ndarray]:
    """Warp one scene's bands and quality asset onto the fixed grid."""
    size = recipe.tile_size_pixels
    bands: list[np.ma.MaskedArray] = []
    for key in recipe.band_assets:
        with (
            rasterio.open(assets[key]) as source,
            WarpedVRT(
                source,
                crs=target_crs,
                transform=target_transform,
                width=size,
                height=size,
                resampling=Resampling.bilinear,
            ) as aligned,
        ):
            bands.append(aligned.read(1, masked=True).astype(np.float32))
    with (
        rasterio.open(assets[recipe.quality_asset]) as source,
        WarpedVRT(
            source,
            crs=target_crs,
            transform=target_transform,
            width=size,
            height=size,
            resampling=Resampling.nearest,
        ) as aligned,
    ):
        quality = aligned.read(1, masked=True)
    valid = quality_mask(recipe.cloud_masking, quality.filled(0).astype(np.uint32))
    valid &= ~np.ma.getmaskarray(quality)
    for band in bands:
        valid &= ~np.ma.getmaskarray(band)
        valid &= np.asarray(band) != recipe.source_no_data_value
    valid_fraction = float(np.count_nonzero(valid) / valid.size)
    if valid_fraction < recipe.minimum_valid_fraction:
        raise WorkerError(
            f"Only {valid_fraction:.1%} of the model context is valid; "
            f"{recipe.minimum_valid_fraction:.1%} is required."
        )
    reflectance = np.stack(
        [
            np.where(valid, np.asarray(band), recipe.source_no_data_value)
            for band in bands
        ],
        axis=0,
    ).astype(np.float32)
    return reflectance, valid


def sar_feature_stack(backscatter: np.ndarray) -> np.ndarray:
    """Derive documented VV, VH, ratio and local-texture features from RTC bands."""
    if backscatter.shape[0] < 2:
        raise WorkerError("SAR fusion requires both VV and VH backscatter bands.")
    vv, vh = backscatter[0], backscatter[1]
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(vh != 0, vv / vh, 0.0)
    texture = _local_standard_deviation(vv)
    return np.stack(
        [vv, vh, np.nan_to_num(ratio, nan=0.0, posinf=0.0, neginf=0.0), texture],
        axis=0,
    ).astype(np.float32)


def _local_standard_deviation(values: np.ndarray, window: int = 3) -> np.ndarray:
    """Compute a fixed-window local standard deviation without extra dependencies."""
    padded = np.pad(values, window // 2, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, (window, window))
    return windows.std(axis=(-2, -1)).astype(np.float32)


def cluster_embeddings(
    features: np.ndarray,
    valid: np.ndarray,
    *,
    max_classes: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Assign each valid sample to a deterministic k-means cluster with a margin score."""
    samples = features[:, valid].T.astype(np.float64)
    if samples.shape[0] < max_classes:
        raise WorkerError(
            f"Only {samples.shape[0]} valid samples remain for {max_classes} classes."
        )
    finite = np.isfinite(samples).all(axis=1)
    samples = samples[finite]
    if samples.shape[0] < max_classes:
        raise WorkerError("Too few finite samples remain after quality masking.")
    centroids = _kmeans_plus_plus(samples, max_classes, seed)
    assignments = np.zeros(samples.shape[0], dtype=np.int64)
    for iteration in range(KMEANS_MAX_ITERATIONS):
        distances = _squared_distances(samples, centroids)
        updated = distances.argmin(axis=1)
        if iteration > 0 and np.array_equal(updated, assignments):
            assignments = updated
            break
        assignments = updated
        for index in range(max_classes):
            members = samples[assignments == index]
            if members.size:
                centroids[index] = members.mean(axis=0)
    distances = _squared_distances(samples, centroids)
    ordered = np.sort(distances, axis=1)
    nearest = np.sqrt(np.maximum(ordered[:, 0], 0.0))
    runner_up = np.sqrt(np.maximum(ordered[:, 1], 0.0)) if max_classes > 1 else nearest
    with np.errstate(divide="ignore", invalid="ignore"):
        margin = np.where(runner_up > 0, 1.0 - nearest / runner_up, 0.0)
    confidence = np.clip(np.nan_to_num(margin, nan=0.0), 0.0, 1.0)

    labels = np.full(valid.shape, -1, dtype=np.int64)
    scores = np.zeros(valid.shape, dtype=np.float32)
    positions = np.flatnonzero(valid.ravel())[finite]
    labels.ravel()[positions] = assignments
    scores.ravel()[positions] = confidence.astype(np.float32)
    return labels, scores


def _kmeans_plus_plus(samples: np.ndarray, clusters: int, seed: int) -> np.ndarray:
    """Seed k-means deterministically so identical requests reproduce identical maps."""
    generator = np.random.default_rng(seed)
    centroids = np.empty((clusters, samples.shape[1]), dtype=np.float64)
    centroids[0] = samples[generator.integers(samples.shape[0])]
    closest = _squared_distances(samples, centroids[:1]).ravel()
    for index in range(1, clusters):
        total = float(closest.sum())
        if total <= 0:
            centroids[index] = samples[generator.integers(samples.shape[0])]
        else:
            centroids[index] = samples[
                generator.choice(samples.shape[0], p=closest / total)
            ]
        closest = np.minimum(
            closest,
            _squared_distances(samples, centroids[index : index + 1]).ravel(),
        )
    return centroids


def _squared_distances(samples: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    """Return the squared Euclidean distance from every sample to every centroid."""
    return np.maximum(
        (samples**2).sum(axis=1)[:, None]
        - 2 * samples @ centroids.T
        + (centroids**2).sum(axis=1)[None, :],
        0.0,
    )


def spectral_signatures(reflectance: np.ndarray, semantics: tuple[str, ...]) -> dict:
    """Compute per-pixel indices used to name clusters, keyed by band semantics."""
    index_of = {name: position for position, name in enumerate(semantics)}
    signatures: dict[str, np.ndarray] = {}

    def normalized(first: str, second: str) -> np.ndarray | None:
        if first not in index_of or second not in index_of:
            return None
        left = reflectance[index_of[first]].astype(np.float64)
        right = reflectance[index_of[second]].astype(np.float64)
        with np.errstate(divide="ignore", invalid="ignore"):
            value = (left - right) / (left + right)
        return np.nan_to_num(value, nan=0.0, posinf=0.0, neginf=0.0)

    for name, (first, second) in SPECTRAL_INDEX_BANDS.items():
        value = normalized(first, second)
        if value is not None:
            signatures[name] = value
    for name in semantics:
        signatures[f"mean_{name.casefold()}"] = reflectance[index_of[name]].astype(
            np.float64
        )
    return signatures


def name_clusters(
    labels: np.ndarray,
    signatures: dict,
    scheme_labels: tuple[dict, ...],
) -> dict[int, dict]:
    """Map each cluster to its closest published label using index signatures."""
    available = list(scheme_labels)
    named: dict[int, dict] = {}
    for cluster in sorted({int(value) for value in np.unique(labels) if value >= 0}):
        members = labels == cluster
        profile = {
            name: float(np.nanmean(values[members])) if members.any() else 0.0
            for name, values in signatures.items()
        }
        choice = _closest_label(profile, available)
        named[cluster] = {
            "label": choice,
            "signature": {
                name: round(value, 4)
                for name, value in profile.items()
                if name in SPECTRAL_INDEX_BANDS
            },
        }
    return named


def _closest_label(profile: dict, scheme_labels: list[dict]) -> dict:
    """Pick the published label whose documented rule best fits a cluster profile."""
    ndvi = profile.get("ndvi", 0.0)
    ndwi = profile.get("ndwi", 0.0)
    nbr = profile.get("nbr", 0.0)
    ranking: list[tuple[float, dict]] = []
    for label in scheme_labels:
        name = label["name"]
        score = CLASS_NAMING_RULES.get(name, lambda *_: 0.0)(ndvi, ndwi, nbr)
        ranking.append((score, label))
    ranking.sort(key=lambda entry: entry[0], reverse=True)
    return ranking[0][1]


def execute_run(
    record: RunRecord,
    service: RunService,
    container,
    *,
    adapter: PlanAuraAdapter | None = None,
) -> RunRecord:
    """Route a claimed run to the executor its request kind requires."""
    executor = (
        process_classification_run
        if isinstance(record.request, ClassifyAoiRequest)
        else process_run
    )
    if adapter is None:
        return executor(record, service, container)
    return executor(record, service, container, adapter=adapter)


def process_run(
    record: RunRecord,
    service: RunService,
    container,
    *,
    adapter: PlanAuraAdapter | None = None,
) -> RunRecord:
    """Execute one persisted run and complete it with citable artefacts."""
    service.transition(
        record.run_id,
        RunStatus.RUNNING,
        progress_pct=5,
        expected_worker_id=record.worker_id,
    )
    descriptor = ModelDescriptor.model_validate(record.selected_model)
    recipe = PreprocessingRecipe.model_validate(record.preprocessing_recipe)
    catalog = get_catalog()
    request = record.request
    try:
        item_a = catalog.get_item_summary(request.item_id_epoch_a)
        item_b = catalog.get_item_summary(request.item_id_epoch_b)
        asset_keys = (*recipe.band_assets, recipe.quality_asset)
        assets_a = catalog.get_signed_assets(request.item_id_epoch_a, asset_keys)
        assets_b = catalog.get_signed_assets(request.item_id_epoch_b, asset_keys)
        prepared = prepare_input(
            assets_a,
            assets_b,
            request.geometry,
            recipe,
            descriptor,
        )
    except WorkerError:
        raise
    except Exception as exc:
        raise RetriableWorkerError(
            "Source imagery could not be prepared."
        ) from exc
    if service.get(record.run_id).status is RunStatus.CANCELLED:
        return service.get(record.run_id)
    service.transition(
        record.run_id,
        RunStatus.RUNNING,
        progress_pct=35,
        expected_worker_id=record.worker_id,
    )
    try:
        distance = (adapter or PlanAuraAdapter(descriptor)).infer(prepared.values)
    except WorkerError:
        raise
    except Exception as exc:
        raise RetriableWorkerError("PlanAura inference could not start.") from exc
    if distance.shape != prepared.aoi_mask.shape:
        raise WorkerError(
            f"Model output shape {distance.shape} does not match {prepared.aoi_mask.shape}."
        )
    distance = np.where(prepared.aoi_mask, distance, np.nan).astype(np.float32)
    if service.get(record.run_id).status is RunStatus.CANCELLED:
        return service.get(record.run_id)
    service.transition(
        record.run_id,
        RunStatus.RUNNING,
        progress_pct=75,
        expected_worker_id=record.worker_id,
    )

    features = vectorize_distance(
        distance,
        transform_value=prepared.transform,
        crs=prepared.crs,
        threshold=request.threshold,
        max_features=request.max_features,
        clip_geometry=request.geometry,
    )
    statistics = summarize_distance(
        distance,
        transform_value=prepared.transform,
        threshold=request.threshold,
    )
    generated_at = datetime.now(UTC)
    with tempfile.TemporaryDirectory() as temporary:
        output_dir = Path(temporary)
        change_map = output_dir / "change_distance.tif"
        polygons = output_dir / "change_polygons.geojson"
        stac_item = output_dir / "stac_item.json"
        evidence_manifest = output_dir / "evidence_manifest.json"
        _write_change_map(change_map, distance, prepared)
        _write_geojson(polygons, features)
        _write_output_stac(
            stac_item,
            record,
            item_a,
            item_b,
            statistics,
            generated_at=generated_at,
        )
        manifest = build_evidence_manifest(
            record,
            item_a,
            item_b,
            statistics,
            {
                "change_distance": change_map,
                "change_polygons": polygons,
                "stac_item": stac_item,
            },
            generated_at=generated_at,
        )
        evidence_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        artifacts = [
            _upload_artifact(container, record, path, kind)
            for path, kind in (
                (change_map, "change_distance"),
                (polygons, "change_polygons"),
                (stac_item, "stac_item"),
                (evidence_manifest, "evidence_manifest"),
            )
        ]
    return service.transition(
        record.run_id,
        RunStatus.COMPLETE,
        artifacts=artifacts,
        statistics=statistics,
        features=features,
        expected_worker_id=record.worker_id,
    )


def process_classification_run(
    record: RunRecord,
    service: RunService,
    container,
    *,
    adapter: PlanAuraAdapter | None = None,
) -> RunRecord:
    """Execute one persisted classification run and complete it with citable artefacts."""
    service.transition(
        record.run_id,
        RunStatus.RUNNING,
        progress_pct=5,
        expected_worker_id=record.worker_id,
    )
    descriptor = ModelDescriptor.model_validate(record.selected_model)
    recipe = PreprocessingRecipe.model_validate(record.preprocessing_recipe)
    scheme = get_class_scheme(recipe.class_scheme_id or "")
    catalog = get_catalog()
    request = record.request
    try:
        summaries = [catalog.get_item_summary(item_id) for item_id in request.item_ids]
        primary_id = next(
            summary.item_id
            for summary in summaries
            if summary.collection == recipe.collection
        )
        prepared = prepare_scene(
            catalog.get_signed_assets(
                primary_id, (*recipe.band_assets, recipe.quality_asset)
            ),
            request.geometry,
            recipe,
            descriptor,
        )
        fusion = _prepare_fusion_scene(catalog, summaries, request, recipe, descriptor)
    except WorkerError:
        raise
    except StopIteration as exc:
        raise WorkerError("No source item matches the admitted collection.") from exc
    except Exception as exc:
        raise RetriableWorkerError("Source imagery could not be prepared.") from exc
    if service.get(record.run_id).status is RunStatus.CANCELLED:
        return service.get(record.run_id)
    service.transition(
        record.run_id,
        RunStatus.RUNNING,
        progress_pct=35,
        expected_worker_id=record.worker_id,
    )
    try:
        embeddings = (adapter or PlanAuraAdapter(descriptor)).embed(
            (fusion or prepared).values
        )
    except WorkerError:
        raise
    except Exception as exc:
        raise RetriableWorkerError("PlanAura inference could not start.") from exc

    features = _build_feature_grid(embeddings, prepared, recipe, fusion)
    analysable = prepared.valid & prepared.aoi_mask
    labels, confidence = cluster_embeddings(
        features,
        analysable,
        max_classes=recipe.max_classes or len(scheme.labels),
        seed=CLASSIFICATION_SEED,
    )
    minimum_confidence = recipe.minimum_confidence or 0.0
    labels = np.where(confidence >= minimum_confidence, labels, -1)
    if service.get(record.run_id).status is RunStatus.CANCELLED:
        return service.get(record.run_id)
    service.transition(
        record.run_id,
        RunStatus.RUNNING,
        progress_pct=75,
        expected_worker_id=record.worker_id,
    )

    scheme_labels = tuple(label.model_dump(mode="json") for label in scheme.labels)
    signatures = spectral_signatures(prepared.reflectance, recipe.band_semantics)
    naming = name_clusters(labels, signatures, scheme_labels)
    class_map = _apply_class_values(labels, naming, scheme.no_data_value)
    statistics = summarize_classes(
        class_map,
        confidence,
        naming,
        scheme=scheme,
        transform_value=prepared.transform,
    )
    vectors = vectorize_classes(
        class_map,
        confidence,
        naming,
        transform_value=prepared.transform,
        crs=prepared.crs,
        scheme=scheme,
        max_features=getattr(request, "max_features", 25),
        clip_geometry=request.geometry,
    )
    generated_at = datetime.now(UTC)
    with tempfile.TemporaryDirectory() as temporary:
        output_dir = Path(temporary)
        class_map_path = output_dir / "class_map.tif"
        polygons = output_dir / "class_polygons.geojson"
        class_statistics = output_dir / "class_statistics.json"
        stac_item = output_dir / "stac_item.json"
        evidence_manifest = output_dir / "evidence_manifest.json"
        _write_class_map(class_map_path, class_map, prepared, scheme)
        _write_geojson(polygons, vectors)
        class_statistics.write_text(
            json.dumps(statistics, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        _write_output_stac(
            stac_item,
            record,
            summaries[0],
            summaries[-1],
            statistics,
            generated_at=generated_at,
        )
        manifest = build_evidence_manifest(
            record,
            summaries[0],
            summaries[-1],
            statistics,
            {
                "class_map": class_map_path,
                "class_polygons": polygons,
                "class_statistics": class_statistics,
                "stac_item": stac_item,
            },
            generated_at=generated_at,
            extra_sources=summaries,
        )
        evidence_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        artifacts = [
            _upload_artifact(container, record, path, kind)
            for path, kind in (
                (class_map_path, "class_map"),
                (polygons, "class_polygons"),
                (class_statistics, "class_statistics"),
                (stac_item, "stac_item"),
                (evidence_manifest, "evidence_manifest"),
            )
        ]
    return service.transition(
        record.run_id,
        RunStatus.COMPLETE,
        artifacts=artifacts,
        statistics=statistics,
        features=vectors,
        expected_worker_id=record.worker_id,
    )


def _prepare_fusion_scene(
    catalog,
    summaries: list[StacItemSummary],
    request,
    recipe: PreprocessingRecipe,
    descriptor: ModelDescriptor,
) -> PreparedScene | None:
    """Read the co-located optical scene a SAR profile must fuse with."""
    if not recipe.fusion_collection or not recipe.fusion_band_assets:
        return None
    fusion_id = next(
        (
            summary.item_id
            for summary in summaries
            if summary.collection == recipe.fusion_collection
        ),
        None,
    )
    if fusion_id is None:
        raise WorkerError("SAR classification requires a co-located optical scene.")
    fusion_recipe = recipe.model_copy(
        update={
            "collection": recipe.fusion_collection,
            "band_assets": recipe.fusion_band_assets,
            "band_semantics": OPTICAL_BAND_SEMANTICS,
            "quality_asset": "SCL",
            "cloud_masking": "sentinel2_scl",
        }
    )
    return prepare_scene(
        catalog.get_signed_assets(
            fusion_id, (*fusion_recipe.band_assets, fusion_recipe.quality_asset)
        ),
        request.geometry,
        fusion_recipe,
        descriptor,
    )


def _build_feature_grid(
    embeddings: np.ndarray,
    prepared: PreparedScene,
    recipe: PreprocessingRecipe,
    fusion: PreparedScene | None,
) -> np.ndarray:
    """Upsample embeddings to the output grid and append SAR features when fusing."""
    height, width = prepared.aoi_mask.shape
    upsampled = _nearest_upsample(embeddings, height, width)
    if fusion is None:
        return upsampled
    sar = sar_feature_stack(prepared.reflectance)
    return np.concatenate([upsampled, _standardize(sar)], axis=0)


def _nearest_upsample(values: np.ndarray, height: int, width: int) -> np.ndarray:
    """Repeat a coarse patch grid onto the full output grid without interpolation."""
    rows = np.minimum((np.arange(height) * values.shape[1]) // height, values.shape[1] - 1)
    columns = np.minimum((np.arange(width) * values.shape[2]) // width, values.shape[2] - 1)
    return values[:, rows][:, :, columns]


def _standardize(values: np.ndarray) -> np.ndarray:
    """Zero-center and unit-scale each feature so fused inputs share a metric."""
    flat = values.reshape(values.shape[0], -1)
    mean = np.nanmean(flat, axis=1)[:, None, None]
    deviation = np.nanstd(flat, axis=1)[:, None, None]
    return np.nan_to_num((values - mean) / np.where(deviation > 0, deviation, 1.0))


def _apply_class_values(
    labels: np.ndarray,
    naming: dict,
    no_data_value: int,
) -> np.ndarray:
    """Translate cluster indices into the published class-scheme values."""
    class_map = np.full(labels.shape, no_data_value, dtype=np.uint8)
    for cluster, naming_entry in naming.items():
        class_map[labels == cluster] = np.uint8(naming_entry["label"]["value"])
    return class_map


def summarize_classes(
    class_map: np.ndarray,
    confidence: np.ndarray,
    naming: dict,
    *,
    scheme,
    transform_value: Affine,
) -> dict:
    """Summarise per-class area, share, and mean confidence for the manifest."""
    pixel_area_m2 = abs(transform_value.a * transform_value.e)
    classified = class_map != scheme.no_data_value
    classified_pixels = int(np.count_nonzero(classified))
    by_value: dict[int, dict] = {}
    for naming_entry in naming.values():
        label = naming_entry["label"]
        value = int(label["value"])
        members = class_map == np.uint8(value)
        pixels = int(np.count_nonzero(members))
        if not pixels:
            continue
        existing = by_value.setdefault(
            value,
            {
                "class_value": value,
                "class_name": label["name"],
                "pixels": 0,
                "area_km2": 0.0,
                "percent_of_classified": 0.0,
                "mean_confidence": 0.0,
            },
        )
        existing["pixels"] = pixels
        existing["area_km2"] = round(pixels * pixel_area_m2 / 1_000_000, 6)
        existing["percent_of_classified"] = (
            round(100.0 * pixels / classified_pixels, 3) if classified_pixels else 0.0
        )
        existing["mean_confidence"] = round(float(confidence[members].mean()), 4)
    return {
        "class_scheme_id": scheme.scheme_id,
        "class_scheme_title": scheme.title,
        "classified_pixels": classified_pixels,
        "unclassified_pixels": int(np.count_nonzero(~classified)),
        "classified_area_km2": round(
            classified_pixels * pixel_area_m2 / 1_000_000, 6
        ),
        "mean_confidence": (
            round(float(confidence[classified].mean()), 4) if classified_pixels else 0.0
        ),
        "classes": [by_value[value] for value in sorted(by_value)],
    }


def vectorize_classes(
    class_map: np.ndarray,
    confidence: np.ndarray,
    naming: dict,
    *,
    transform_value: Affine,
    crs: object,
    scheme,
    max_features: int,
    clip_geometry: dict | None = None,
) -> list[dict]:
    """Convert the class raster into ranked WGS84 polygons carrying confidence."""
    if max_features <= 0:
        return []
    names = {
        int(entry["label"]["value"]): entry["label"]["name"] for entry in naming.values()
    }
    colours = {int(label.value): label.colour for label in scheme.labels}
    projected_clip = (
        shape(transform_geom("EPSG:4326", crs, clip_geometry, precision=7))
        if clip_geometry is not None
        else None
    )
    simplification_tolerance = max(abs(transform_value.a), abs(transform_value.e)) / 2
    candidates: list[tuple[float, int, dict]] = []
    mask = class_map != np.uint8(scheme.no_data_value)
    for index, (geometry, raw_value) in enumerate(
        shapes(class_map, mask=mask, transform=transform_value)
    ):
        class_value = int(raw_value)
        polygon = shape(geometry)
        if projected_clip is not None:
            polygon = polygon.intersection(projected_clip)
        if polygon.is_empty:
            continue
        polygon = polygon.simplify(simplification_tolerance, preserve_topology=True)
        if polygon.is_empty:
            continue
        members = (class_map == np.uint8(class_value)) & mask
        wgs84 = shape(transform_geom(crs, "EPSG:4326", mapping(polygon), precision=7))
        area_m2, _ = GEOD.geometry_area_perimeter(wgs84)
        candidates.append(
            (
                abs(area_m2),
                index,
                {
                    "type": "Feature",
                    "geometry": mapping(wgs84),
                    "properties": {
                        "class_value": class_value,
                        "class_name": names.get(class_value, "unnamed_cluster"),
                        "class_colour": colours.get(class_value),
                        "class_scheme_id": scheme.scheme_id,
                        "area_km2": round(abs(area_m2) / 1_000_000, 6),
                        "mean_confidence": round(
                            float(confidence[members].mean()) if members.any() else 0.0,
                            4,
                        ),
                    },
                },
            )
        )
    ranked = heapq.nlargest(max_features, candidates, key=lambda entry: (entry[0], -entry[1]))
    return [feature for _, _, feature in ranked]


def _write_class_map(
    path: Path,
    class_map: np.ndarray,
    prepared: PreparedScene,
    scheme,
) -> None:
    """Write the paletted single-band class COG with its published colour table."""
    with rasterio.open(
        path,
        "w",
        driver="COG",
        width=class_map.shape[1],
        height=class_map.shape[0],
        count=1,
        dtype="uint8",
        crs=prepared.crs,
        transform=prepared.transform,
        compress="DEFLATE",
        nodata=scheme.no_data_value,
    ) as destination:
        destination.write(class_map, 1)
        destination.write_colormap(
            1,
            {
                int(label.value): (
                    int(label.colour[1:3], 16),
                    int(label.colour[3:5], 16),
                    int(label.colour[5:7], 16),
                    255,
                )
                for label in scheme.labels
            },
        )


def build_evidence_manifest(
    record: RunRecord,
    item_a: StacItemSummary,
    item_b: StacItemSummary,
    statistics: dict,
    outputs: dict[str, Path],
    *,
    generated_at: datetime,
    extra_sources: list[StacItemSummary] | None = None,
) -> dict[str, object]:
    """Build a reproducible evidence record without raster bytes."""
    sources = extra_sources if extra_sources is not None else [item_a, item_b]
    return {
        "schema_version": "planetary-explorer.geofm.evidence.v1",
        "run": {
            "run_id": str(record.run_id),
            "created_at": record.created_at.isoformat(),
            "updated_at": generated_at.isoformat(),
            "correlation_id": record.request.correlation_id,
            "requested_by": record.request.requested_by,
        },
        "request": record.request.model_dump(mode="json"),
        "sources": [
            {
                "item_id": item.item_id,
                "collection": item.collection,
                "acquired_at": item.acquired_at.isoformat(),
            }
            for item in sources
        ],
        "model": record.selected_model,
        "classifier_head": (
            record.selected_model.get("classifier_head")
            if isinstance(record.selected_model, dict)
            else None
        ),
        "class_scheme_id": (
            record.preprocessing_recipe.get("class_scheme_id")
            if isinstance(record.preprocessing_recipe, dict)
            else None
        ),
        "preprocessing": record.preprocessing_recipe,
        "statistics": statistics,
        "warnings": record.warnings,
        "outputs": [
            {
                "kind": kind,
                "filename": output.name,
                "size_bytes": output.stat().st_size,
                "sha256": _sha256_file(output),
            }
            for kind, output in sorted(outputs.items())
        ],
    }


def validate_asset_url(url: str) -> None:
    """Reject arbitrary or unsigned URLs before GDAL opens them."""
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or not any(
        hostname.endswith(suffix) for suffix in ALLOWED_ASSET_HOST_SUFFIXES
    ):
        raise WorkerError("Raster assets must use HTTPS on an approved blob host.")
    if not parsed.query:
        raise WorkerError("Raster asset URL must include a short-lived signature.")


def sanitize_error(error: Exception) -> str:
    """Remove signed query strings before logging or persisting an error."""
    message = str(error)
    message = re.sub(
        r"(https://[^\s?'\"<>]+)\?[^\s'\"<>]+",
        r"\1?<redacted>",
        message,
    )
    return message[:2000]


def _close_worker_clients(*clients) -> None:
    for client in clients:
        if client is None:
            continue
        try:
            client.close()
        except Exception as error:
            logger.warning("GeoFM worker client cleanup failed: %s", sanitize_error(error))


def run_one_message() -> bool:
    """Consume and acknowledge at most one Azure Queue message."""
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import ContainerClient
    from azure.storage.queue import QueueClient

    credential = None
    container = None
    queue = None
    poison_queue = None
    try:
        credential = DefaultAzureCredential()
        blob_url = os.environ["AZURE_STORAGE_BLOB_ENDPOINT"]
        queue_url = os.environ["AZURE_STORAGE_QUEUE_ENDPOINT"]
        container = ContainerClient(
            account_url=blob_url,
            container_name=os.getenv("GEOFM_CONTAINER_NAME", "geofm"),
            credential=credential,
        )
        queue = QueueClient(
            account_url=queue_url,
            queue_name=os.getenv("GEOFM_QUEUE_NAME", "geofm-jobs"),
            credential=credential,
        )
        poison_queue = QueueClient(
            account_url=queue_url,
            queue_name=os.getenv("GEOFM_POISON_QUEUE_NAME", "geofm-poison"),
            credential=credential,
        )
        service = RunService(
            BlobRunRepository(container),
            NoopDispatcher(),
            inventory_lookup=get_catalog().get_asset_inventory,
            allow_conditional_models=True,
        )
        return consume_one_message(queue, service, container, poison_queue=poison_queue)
    finally:
        _close_worker_clients(poison_queue, queue, container, credential)


def _quarantine_message(
    poison_queue,
    message,
    run_id: UUID | None,
    error: Exception,
    dequeue_count: int,
) -> bool:
    if poison_queue is None:
        return False
    try:
        poison_queue.send_message(
            json.dumps(
                {
                    "run_id": str(run_id) if run_id else None,
                    "message_sha256": hashlib.sha256(
                        str(message.content).encode("utf-8")
                    ).hexdigest(),
                    "dequeue_count": dequeue_count,
                    "error": sanitize_error(error),
                    "quarantined_at": datetime.now(UTC).isoformat(),
                }
            )
        )
        return True
    except Exception as quarantine_error:
        logger.error(
            "GeoFM worker could not quarantine an exhausted message: %s",
            sanitize_error(quarantine_error),
        )
        return False


def consume_one_message(
    queue,
    service: RunService,
    container,
    *,
    poison_queue=None,
) -> bool:
    """Process one queue message and acknowledge only after durable resolution."""
    lease_seconds = min(
        604800,
        max(60, int(os.getenv("GEOFM_WORKER_LEASE_SECONDS", "21600"))),
    )
    message = next(
        iter(
            queue.receive_messages(
                messages_per_page=1,
                visibility_timeout=lease_seconds,
            )
        ),
        None,
    )
    if message is None:
        return False

    record: RunRecord | None = None
    should_delete = False
    max_dequeue_count = int(os.getenv("GEOFM_MAX_DEQUEUE_COUNT", "5"))
    dequeue_count = int(getattr(message, "dequeue_count", 1) or 1)
    try:
        payload = json.loads(message.content)
        run_id = UUID(payload["run_id"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.error(
            "GeoFM worker received an invalid queue message: %s",
            sanitize_error(exc),
        )
        if _quarantine_message(poison_queue, message, None, exc, dequeue_count):
            queue.delete_message(message)
        return True

    try:
        record = service.get(run_id)
        if record.status in {RunStatus.QUEUED, RunStatus.RUNNING}:
            if isinstance(service, RunService):
                record = service.try_claim(
                    run_id,
                    WORKER_ID,
                    lease_seconds=lease_seconds,
                )
            if record is None:
                should_delete = False
            else:
                execute_run(record, service, container)
                should_delete = True
        elif record.status is RunStatus.FAILED:
            should_delete = _quarantine_message(
                poison_queue,
                message,
                run_id,
                RuntimeError(record.error or "Failed run awaiting quarantine."),
                dequeue_count,
            )
        else:
            should_delete = True
    except (RunConflict, RunRepositoryError, RetriableWorkerError) as exc:
        if dequeue_count < max_dequeue_count:
            logger.warning(
                "GeoFM worker retained a queued run after a retriable failure: %s",
                sanitize_error(exc),
            )
        else:
            logger.error(
                "GeoFM worker exhausted %d attempts for a retriable failure: %s",
                dequeue_count,
                sanitize_error(exc),
            )
            if record and record.status not in TERMINAL_STATUSES:
                try:
                    service.transition(
                        record.run_id,
                        RunStatus.FAILED,
                        error=sanitize_error(exc),
                        expected_worker_id=record.worker_id,
                    )
                except Exception as persistence_error:
                    logger.error(
                        "GeoFM worker could not persist exhausted retry state: %s",
                        sanitize_error(persistence_error),
                    )
            should_delete = _quarantine_message(
                poison_queue,
                message,
                run_id,
                exc,
                dequeue_count,
            )
    except Exception as exc:
        logger.error("GeoFM worker failed a queued run: %s", sanitize_error(exc))
        if record and record.status not in TERMINAL_STATUSES:
            try:
                service.transition(
                    record.run_id,
                    RunStatus.FAILED,
                    error=sanitize_error(exc),
                    expected_worker_id=record.worker_id,
                )
            except Exception as persistence_error:
                logger.error(
                    "GeoFM worker could not persist failure state: %s",
                    sanitize_error(persistence_error),
                )
            should_delete = _quarantine_message(
                poison_queue,
                message,
                run_id,
                exc,
                dequeue_count,
            )
        elif isinstance(exc, RunNotFound) and dequeue_count >= max_dequeue_count:
            should_delete = _quarantine_message(
                poison_queue,
                message,
                run_id,
                exc,
                dequeue_count,
            )
            logger.error(
                "GeoFM worker quarantined a missing-run message after %d attempts.",
                dequeue_count,
            )
        elif record is None and dequeue_count >= max_dequeue_count:
            should_delete = _quarantine_message(
                poison_queue,
                message,
                run_id,
                exc,
                dequeue_count,
            )
        if not should_delete and dequeue_count >= max_dequeue_count:
            should_delete = _quarantine_message(
                poison_queue,
                message,
                run_id,
                exc,
                dequeue_count,
            )
    finally:
        if should_delete:
            try:
                queue.delete_message(message)
            except Exception as error:
                logger.warning(
                    "GeoFM worker could not acknowledge a resolved message: %s",
                    sanitize_error(error),
                )
    return True


def main() -> None:
    """Continuously consume work while the queue-scaled replica is active."""
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    idle_seconds = float(os.getenv("GEOFM_IDLE_POLL_SECONDS", "5"))
    while True:
        if not run_one_message():
            time.sleep(idle_seconds)


def _read_epoch(
    assets: dict[str, str],
    target_crs: object,
    target_transform: Affine,
    recipe: PreprocessingRecipe,
) -> np.ndarray:
    size = recipe.tile_size_pixels
    bands: list[np.ma.MaskedArray] = []
    for key in recipe.band_assets:
        with (
            rasterio.open(assets[key]) as source,
            WarpedVRT(
                source,
                crs=target_crs,
                transform=target_transform,
                width=size,
                height=size,
                resampling=Resampling.bilinear,
            ) as aligned,
        ):
            bands.append(aligned.read(1, masked=True).astype(np.float32))
    with (
        rasterio.open(assets[recipe.quality_asset]) as source,
        WarpedVRT(
            source,
            crs=target_crs,
            transform=target_transform,
            width=size,
            height=size,
            resampling=Resampling.nearest,
        ) as aligned,
    ):
        quality = aligned.read(1, masked=True)
    valid = valid_hls_fmask(quality.filled(255).astype(np.uint8))
    valid &= ~np.ma.getmaskarray(quality)
    for band in bands:
        valid &= ~np.ma.getmaskarray(band)
        valid &= np.asarray(band) != recipe.source_no_data_value
    valid_fraction = float(np.count_nonzero(valid) / valid.size)
    if valid_fraction < recipe.minimum_valid_fraction:
        raise WorkerError(
            f"Only {valid_fraction:.1%} of the model context is valid; "
            f"{recipe.minimum_valid_fraction:.1%} is required."
        )
    return np.stack(
        [
            np.where(valid, np.asarray(band), recipe.source_no_data_value)
            for band in bands
        ],
        axis=0,
    ).astype(np.float32)


def _write_change_map(path: Path, values: np.ndarray, prepared: PreparedInput) -> None:
    with rasterio.open(
        path,
        "w",
        driver="COG",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="float32",
        crs=prepared.crs,
        transform=prepared.transform,
        compress="DEFLATE",
        nodata=-9999,
    ) as destination:
        destination.write(np.where(np.isfinite(values), values, -9999).astype(np.float32), 1)


def _write_geojson(path: Path, features: list[dict]) -> None:
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )


def _write_output_stac(
    path: Path,
    record: RunRecord,
    item_a: StacItemSummary,
    item_b: StacItemSummary,
    statistics: dict,
    *,
    generated_at: datetime,
) -> None:
    item = {
        "stac_version": "1.0.0",
        "type": "Feature",
        "id": str(record.run_id),
        "geometry": record.request.geometry,
        "bbox": list(shape(record.request.geometry).bounds),
        "properties": {
            "datetime": generated_at.isoformat(),
            "planetary-explorer:model": record.selected_model["model_id"],
            "planetary-explorer:model_revision": record.selected_model["model_revision"],
            "planetary-explorer:checkpoint_sha256": record.selected_model[
                "checkpoint_sha256"
            ],
            "planetary-explorer:source_items": [item_a.item_id, item_b.item_id],
            "planetary-explorer:preprocessing": record.preprocessing_recipe,
            **statistics,
        },
        "links": [],
        "assets": {
            "change_distance": {
                "href": "change_distance.tif",
                "type": "image/tiff; application=geotiff",
            },
            "change_polygons": {
                "href": "change_polygons.geojson",
                "type": "application/geo+json",
            },
        },
    }
    path.write_text(json.dumps(item), encoding="utf-8")


def _upload_artifact(
    container,
    run: RunRecord | UUID,
    path: Path,
    kind: str,
) -> RunArtifact:
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if isinstance(run, RunRecord):
        run_id = run.run_id
        worker_key = hashlib.sha256(
            (run.worker_id or f"version-{run.version}").encode("utf-8")
        ).hexdigest()[:16]
        blob_name = (
            f"runs/{run_id}/attempts/{run.attempt}/workers/{worker_key}/"
            f"{digest}/{path.name}"
        )
    else:
        run_id = run
        blob_name = f"runs/{run_id}/legacy/{digest}/{path.name}"
    blob = container.get_blob_client(blob_name)
    try:
        blob.upload_blob(
            content,
            overwrite=False,
            metadata={"sha256": digest},
        )
    except Exception as exc:
        if getattr(exc, "status_code", None) != 409:
            raise RunRepositoryError(
                f"Artifact '{path.name}' could not be uploaded."
            ) from exc
        try:
            properties = blob.get_blob_properties()
            metadata = getattr(properties, "metadata", None)
            if metadata is None and isinstance(properties, dict):
                metadata = properties.get("metadata")
        except Exception as metadata_error:
            raise RunRepositoryError(
                f"Artifact '{path.name}' exists but could not be verified."
            ) from metadata_error
        if not isinstance(metadata, dict) or metadata.get("sha256") != digest:
            raise RunRepositoryError(
                f"Artifact '{path.name}' already exists with different content."
            ) from exc
    return RunArtifact(
        kind=kind,
        uri=urljoin(container.url.rstrip("/") + "/", blob_name),
        sha256=digest,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


TERMINAL_STATUSES = {RunStatus.COMPLETE, RunStatus.FAILED, RunStatus.CANCELLED}


if __name__ == "__main__":
    main()