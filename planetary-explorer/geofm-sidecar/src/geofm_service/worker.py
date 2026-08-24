"""Queue-driven PlanAura worker that produces bounded geospatial evidence."""

from __future__ import annotations

import hashlib
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
from uuid import UUID

import numpy as np
import rasterio
from affine import Affine
from pyproj import Geod
from rasterio.features import geometry_mask, shapes
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling, transform_geom
from shapely.geometry import shape

from .contracts import RunArtifact, RunRecord, RunStatus
from .jobs import BlobRunRepository, NoopDispatcher, PreprocessingRecipe, RunService
from .model import PlanAuraAdapter, normalize_epochs
from .policy import ModelDescriptor
from .stac import StacItemSummary, get_catalog

logger = logging.getLogger(__name__)
GEOD = Geod(ellps="WGS84")
UTC = timezone.utc
ALLOWED_ASSET_HOST_SUFFIXES = (".blob.core.windows.net",)


class WorkerError(RuntimeError):
    """Raised when a run cannot produce reproducible evidence."""


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
    contaminated = (values & np.uint8(0b0001_1110)) != 0
    high_aerosol = ((values >> np.uint8(6)) & np.uint8(0b11)) == 0b11
    return ~(contaminated | high_aerosol)


def vectorize_distance(
    values: np.ndarray,
    *,
    transform_value: Affine,
    crs: object,
    threshold: float,
    max_features: int,
) -> list[dict]:
    """Convert thresholded model distance into ranked WGS84 polygons."""
    valid = np.isfinite(values)
    selected = valid & (values >= threshold)
    selected_values = selected.astype(np.uint8)
    features: list[dict] = []
    for projected_geometry, value in shapes(
        selected_values,
        mask=selected,
        transform=transform_value,
        connectivity=8,
    ):
        if int(value) != 1:
            continue
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
    )[:max_features]
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


def process_run(
    record: RunRecord,
    service: RunService,
    container,
    *,
    adapter: PlanAuraAdapter | None = None,
) -> RunRecord:
    """Execute one persisted run and complete it with citable artefacts."""
    service.transition(record.run_id, RunStatus.RUNNING, progress_pct=5)
    descriptor = ModelDescriptor.model_validate(record.selected_model)
    recipe = PreprocessingRecipe.model_validate(record.preprocessing_recipe)
    catalog = get_catalog()
    request = record.request
    item_a = catalog.get_item_summary(request.item_id_epoch_a)
    item_b = catalog.get_item_summary(request.item_id_epoch_b)
    asset_keys = (*recipe.band_assets, recipe.quality_asset)
    assets_a = catalog.get_signed_assets(request.item_id_epoch_a, asset_keys)
    assets_b = catalog.get_signed_assets(request.item_id_epoch_b, asset_keys)
    prepared = prepare_input(assets_a, assets_b, request.geometry, recipe, descriptor)
    if service.get(record.run_id).status is RunStatus.CANCELLED:
        return service.get(record.run_id)
    service.transition(record.run_id, RunStatus.RUNNING, progress_pct=35)
    distance = (adapter or PlanAuraAdapter(descriptor)).infer(prepared.values)
    if distance.shape != prepared.aoi_mask.shape:
        raise WorkerError(
            f"Model output shape {distance.shape} does not match {prepared.aoi_mask.shape}."
        )
    distance = np.where(prepared.aoi_mask, distance, np.nan).astype(np.float32)
    if service.get(record.run_id).status is RunStatus.CANCELLED:
        return service.get(record.run_id)
    service.transition(record.run_id, RunStatus.RUNNING, progress_pct=75)

    features = vectorize_distance(
        distance,
        transform_value=prepared.transform,
        crs=prepared.crs,
        threshold=request.threshold,
        max_features=request.max_features,
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
            _upload_artifact(container, record.run_id, path, kind)
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
    )


def build_evidence_manifest(
    record: RunRecord,
    item_a: StacItemSummary,
    item_b: StacItemSummary,
    statistics: dict,
    outputs: dict[str, Path],
    *,
    generated_at: datetime,
) -> dict[str, object]:
    """Build a reproducible evidence record without raster bytes."""
    return {
        "schema_version": "planetary-explorer.geofm.evidence.v1",
        "run": {
            "run_id": str(record.run_id),
            "created_at": record.created_at.isoformat(),
            "updated_at": generated_at.isoformat(),
            "correlation_id": record.request.correlation_id,
            "requested_by": record.request.requested_by,
        },
        "request": {
            "geometry": record.request.geometry,
            "threshold": record.request.threshold,
            "max_features": record.request.max_features,
            "profile": record.request.profile,
        },
        "sources": [
            {
                "item_id": item.item_id,
                "collection": item.collection,
                "acquired_at": item.acquired_at.isoformat(),
            }
            for item in (item_a, item_b)
        ],
        "model": record.selected_model,
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


def run_one_message() -> bool:
    """Consume and acknowledge at most one Azure Queue message."""
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import ContainerClient
    from azure.storage.queue import QueueClient

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
    service = RunService(
        BlobRunRepository(container),
        NoopDispatcher(),
        inventory_lookup=get_catalog().get_asset_inventory,
        allow_conditional_models=True,
    )
    return consume_one_message(queue, service, container)


def consume_one_message(queue, service: RunService, container) -> bool:
    """Process one queue message and acknowledge only after durable resolution."""
    message = next(
        iter(queue.receive_messages(messages_per_page=1, visibility_timeout=1800)),
        None,
    )
    if message is None:
        return False

    record: RunRecord | None = None
    should_delete = False
    try:
        payload = json.loads(message.content)
        record = service.get(UUID(payload["run_id"]))
        # A redelivered running record means the prior queue visibility lease
        # expired. Restart the idempotent run; version checks protect cancel.
        if record.status in {RunStatus.QUEUED, RunStatus.RUNNING}:
            process_run(record, service, container)
        should_delete = True
    except Exception as exc:
        logger.error("GeoFM worker failed a queued run: %s", sanitize_error(exc))
        if record and record.status not in TERMINAL_STATUSES:
            try:
                service.transition(
                    record.run_id,
                    RunStatus.FAILED,
                    error=sanitize_error(exc),
                )
                should_delete = True
            except Exception as persistence_error:
                logger.error(
                    "GeoFM worker could not persist failure state: %s",
                    sanitize_error(persistence_error),
                )
    finally:
        if should_delete:
            queue.delete_message(message)
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


def _upload_artifact(container, run_id: UUID, path: Path, kind: str) -> RunArtifact:
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    blob_name = f"runs/{run_id}/{path.name}"
    container.get_blob_client(blob_name).upload_blob(content, overwrite=True)
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