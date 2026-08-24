"""Fail-closed admission and durable orchestration for GeoFM runs."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from azure.core import MatchConditions
from azure.core.exceptions import ResourceModifiedError
from pydantic import BaseModel, ConfigDict, Field
from pyproj import CRS, Geod, Transformer
from shapely import box
from shapely.geometry import shape
from shapely.ops import transform

from .contracts import CompareEpochsRequest, RunArtifact, RunRecord, RunStatus
from .policy import ApprovalState, ModelDescriptor, get_model

GEOD = Geod(ellps="WGS84")
CANADA_ENVELOPE = box(-141.1, 41.6, -52.5, 83.2)
TERMINAL_STATUSES = {RunStatus.COMPLETE, RunStatus.FAILED, RunStatus.CANCELLED}
ALLOWED_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED},
    RunStatus.RUNNING: {
        RunStatus.RUNNING,
        RunStatus.COMPLETE,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
    },
    RunStatus.COMPLETE: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
}


class RunError(ValueError):
    """Raised when admission or a lifecycle transition fails."""


class RunConflict(RunError):
    """Raised when a concurrent writer changed a run first."""


class ImageryObservation(BaseModel):
    """Server-derived STAC metadata used for model admission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str = Field(min_length=1, max_length=512)
    collection: str = Field(min_length=1, max_length=256)
    asset_keys: frozenset[str] = Field(min_length=1)
    resolution_m: float = Field(gt=0)
    acquired_at: datetime
    tile_id: str | None = None
    geometry: dict


class PreprocessingRecipe(BaseModel):
    """Immutable recipe persisted after both epochs pass admission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    collection: str
    band_assets: tuple[str, ...]
    band_semantics: tuple[str, ...] = (
        "BLUE",
        "GREEN",
        "RED",
        "NIR_NARROW",
        "SWIR_1",
        "SWIR_2",
    )
    quality_asset: str
    target_resolution_m: float
    tile_size_pixels: int
    patch_stride_pixels: int
    normalization_mean: tuple[float, ...]
    normalization_std: tuple[float, ...]
    source_no_data_value: float
    model_no_data_value: float
    minimum_valid_fraction: float
    alignment: str = "fixed_grid_centered_on_aoi"
    reflectance_resampling: str = "bilinear"
    mask_resampling: str = "nearest"
    cloud_masking: str = "hls_fmask"
    output_metric: str = "cosine_distance"


class CompatibilityDecision(BaseModel):
    """Admission outcome for a pair of imagery observations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    compatible: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    recipe: PreprocessingRecipe | None = None


class AoiValidation(BaseModel):
    """Validated AOI dimensions relative to the fixed PlanAura context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    area_km2: float
    width_m: float
    height_m: float
    within_training_envelope: bool
    warnings: tuple[str, ...] = ()


class RunRepository(Protocol):
    """Persistence boundary for durable runs."""

    def create_or_get(self, record: RunRecord) -> tuple[RunRecord, bool]: ...

    def get(self, run_id: UUID) -> RunRecord | None: ...

    def save(self, record: RunRecord, *, expected_version: int) -> None: ...


class RunDispatcher(Protocol):
    """Queue boundary invoked after durable persistence."""

    def dispatch(self, record: RunRecord) -> None: ...


class NoopDispatcher:
    """Keep local runs queued without external work dispatch."""

    def dispatch(self, record: RunRecord) -> None:
        """Accept a persisted run without external side effects."""


class InMemoryRunRepository:
    """Deterministic repository for unit tests and local probes."""

    def __init__(self) -> None:
        self._records: dict[UUID, RunRecord] = {}
        self._by_idempotency: dict[str, UUID] = {}
        self._lock = threading.RLock()

    def create_or_get(self, record: RunRecord) -> tuple[RunRecord, bool]:
        with self._lock:
            existing_id = self._by_idempotency.get(record.idempotency_key)
            if existing_id is not None:
                return self._records[existing_id].model_copy(deep=True), False
            self._records[record.run_id] = record.model_copy(deep=True)
            self._by_idempotency[record.idempotency_key] = record.run_id
            return record.model_copy(deep=True), True

    def get(self, run_id: UUID) -> RunRecord | None:
        with self._lock:
            record = self._records.get(run_id)
            return record.model_copy(deep=True) if record else None

    def save(self, record: RunRecord, *, expected_version: int) -> None:
        with self._lock:
            current = self._records.get(record.run_id)
            if current is None:
                raise RunError(f"Run '{record.run_id}' does not exist.")
            if current.version != expected_version:
                raise RunConflict(f"Run '{record.run_id}' changed concurrently.")
            self._records[record.run_id] = record.model_copy(deep=True)


class SQLiteRunRepository:
    """Local durable repository with an idempotency constraint."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS geofm_runs (
                    run_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    version INTEGER NOT NULL DEFAULT 0,
                    record_json TEXT NOT NULL
                )
                """
            )
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(geofm_runs)")
            }
            if "version" not in columns:
                connection.execute(
                    "ALTER TABLE geofm_runs ADD COLUMN version INTEGER NOT NULL DEFAULT 0"
                )

    def create_or_get(self, record: RunRecord) -> tuple[RunRecord, bool]:
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO geofm_runs(run_id, idempotency_key, version, record_json) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        str(record.run_id),
                        record.idempotency_key,
                        record.version,
                        record.model_dump_json(),
                    ),
                )
                return record, True
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT record_json FROM geofm_runs WHERE idempotency_key = ?",
                    (record.idempotency_key,),
                ).fetchone()
                if row is None:
                    raise RunError(
                        "Idempotency collision occurred without an existing run."
                    ) from None
                return RunRecord.model_validate_json(row[0]), False

    def get(self, run_id: UUID) -> RunRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM geofm_runs WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()
        return RunRecord.model_validate_json(row[0]) if row else None

    def save(self, record: RunRecord, *, expected_version: int) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE geofm_runs SET version = ?, record_json = ? "
                "WHERE run_id = ? AND version = ?",
                (
                    record.version,
                    record.model_dump_json(),
                    str(record.run_id),
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                if self.get(record.run_id) is None:
                    raise RunError(f"Run '{record.run_id}' does not exist.")
                raise RunConflict(f"Run '{record.run_id}' changed concurrently.")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)


class BlobRunRepository:
    """Azure Blob repository with immutable idempotency pointers."""

    def __init__(self, container) -> None:
        self._container = container
        self._etags: dict[tuple[UUID, int], str] = {}

    def create_or_get(self, record: RunRecord) -> tuple[RunRecord, bool]:
        run_blob = self._container.get_blob_client(f"runs/{record.run_id}/run.json")
        pointer_blob = self._container.get_blob_client(
            f"idempotency/{record.idempotency_key}.json"
        )
        run_blob.upload_blob(record.model_dump_json(), overwrite=False)
        try:
            pointer_blob.upload_blob(
                json.dumps({"run_id": str(record.run_id)}),
                overwrite=False,
            )
            return record, True
        except Exception as exc:
            if getattr(exc, "status_code", None) != 409:
                raise
            run_blob.delete_blob(delete_snapshots="include")
            pointer = json.loads(pointer_blob.download_blob().readall())
            existing = self.get(UUID(pointer["run_id"]))
            if existing is None:
                raise RunError("Idempotency pointer refers to a missing run.") from None
            return existing, False

    def get(self, run_id: UUID) -> RunRecord | None:
        blob = self._container.get_blob_client(f"runs/{run_id}/run.json")
        try:
            download = blob.download_blob()
            content = download.readall()
        except Exception as exc:
            if getattr(exc, "status_code", None) == 404:
                return None
            raise
        properties = download.properties
        etag = getattr(properties, "etag", None)
        if etag is None and isinstance(properties, dict):
            etag = properties.get("etag")
        if not etag:
            raise RunError(f"Run '{run_id}' was loaded without an ETag.")
        record = RunRecord.model_validate_json(content)
        self._etags[(run_id, record.version)] = str(etag)
        return record

    def save(self, record: RunRecord, *, expected_version: int) -> None:
        etag = self._etags.get((record.run_id, expected_version))
        if not etag:
            raise RunConflict(f"Run '{record.run_id}' has no concurrency token.")
        blob = self._container.get_blob_client(f"runs/{record.run_id}/run.json")
        try:
            response = blob.upload_blob(
                record.model_dump_json(),
                overwrite=True,
                etag=etag,
                match_condition=MatchConditions.IfNotModified,
            )
        except ResourceModifiedError as exc:
            raise RunConflict(f"Run '{record.run_id}' changed concurrently.") from exc
        new_etag = response.get("etag") if isinstance(response, dict) else None
        if new_etag:
            self._etags[(record.run_id, record.version)] = str(new_etag)


class AzureQueueDispatcher:
    """Dispatch durable run identifiers to Azure Queue Storage."""

    def __init__(self, queue) -> None:
        self._queue = queue

    def dispatch(self, record: RunRecord) -> None:
        """Send only the persisted run identifier to the worker."""
        self._queue.send_message(json.dumps({"run_id": str(record.run_id)}))


class RunService:
    """Admit, persist, dispatch, and transition GeoFM runs."""

    def __init__(
        self,
        repository: RunRepository,
        dispatcher: RunDispatcher,
        *,
        inventory_lookup: Callable[[str], ImageryObservation],
        allow_conditional_models: bool = False,
    ) -> None:
        self._repository = repository
        self._dispatcher = dispatcher
        self._inventory_lookup = inventory_lookup
        self._allow_conditional_models = allow_conditional_models

    def submit(self, request: CompareEpochsRequest) -> tuple[RunRecord, bool]:
        """Validate, persist, and dispatch an idempotent comparison run."""
        descriptor = get_model(request.profile)
        if descriptor.approval_state is ApprovalState.BLOCKED:
            raise RunError(f"Model profile '{request.profile}' is blocked.")
        if (
            descriptor.approval_state is ApprovalState.CONDITIONAL
            and not self._allow_conditional_models
        ):
            raise RunError(
                f"Model profile '{request.profile}' requires explicit deployment approval."
            )
        aoi = validate_aoi(request.geometry, descriptor)
        observations = (
            self._inventory_lookup(request.item_id_epoch_a),
            self._inventory_lookup(request.item_id_epoch_b),
        )
        requested_shape = shape(request.geometry)
        if any(
            not shape(observation.geometry).covers(requested_shape)
            for observation in observations
        ):
            raise RunError("AOI is not fully covered by both source items.")
        compatibility = resolve_compatibility(descriptor, observations)
        if not compatibility.compatible or compatibility.recipe is None:
            raise RunError(
                "Imagery is incompatible with PlanAura: "
                + ", ".join(compatibility.errors)
                + "."
            )
        warnings = [*aoi.warnings, *compatibility.warnings]
        record = RunRecord(
            idempotency_key=_request_hash(request),
            request=request,
            selected_model=descriptor.model_dump(mode="json"),
            preprocessing_recipe=compatibility.recipe.model_dump(mode="json"),
            warnings=warnings,
        )
        stored, created = self._repository.create_or_get(record)
        if created or stored.status is RunStatus.QUEUED:
            try:
                self._dispatcher.dispatch(stored)
            except Exception as exc:
                self.transition(stored.run_id, RunStatus.FAILED, error=str(exc))
                raise RunError("Run persisted but queue dispatch failed.") from exc
        return stored, created

    def get(self, run_id: UUID) -> RunRecord:
        """Return one durable run or raise a specific error."""
        record = self._repository.get(run_id)
        if record is None:
            raise RunError(f"Run '{run_id}' was not found.")
        return record

    def get_for_owner(self, run_id: UUID, requested_by: str) -> RunRecord:
        """Return a run only when its persisted owner matches the caller."""
        record = self.get(run_id)
        if not hmac.compare_digest(record.request.requested_by, requested_by):
            raise RunError(f"Run '{run_id}' was not found.")
        return record

    def transition(
        self,
        run_id: UUID,
        status: RunStatus,
        *,
        progress_pct: int | None = None,
        error: str | None = None,
        artifacts: list[RunArtifact] | None = None,
        statistics: dict | None = None,
        features: list[dict] | None = None,
    ) -> RunRecord:
        """Apply a valid lifecycle transition and persist it."""
        record = self.get(run_id)
        expected_version = record.version
        if status not in ALLOWED_TRANSITIONS[record.status]:
            raise RunError(f"Invalid run transition from '{record.status}' to '{status}'.")
        record.status = status
        record.progress_pct = (
            100
            if status is RunStatus.COMPLETE
            else (progress_pct if progress_pct is not None else record.progress_pct)
        )
        record.error = error
        if artifacts is not None:
            record.artifacts = artifacts
        if statistics is not None:
            record.statistics = statistics
        if features is not None:
            record.features = features
        record.version = expected_version + 1
        record.updated_at = datetime.now(UTC)
        self._repository.save(record, expected_version=expected_version)
        return record

    def cancel(self, run_id: UUID) -> RunRecord:
        """Cancel a queued or running run."""
        record = self.get(run_id)
        if record.status in TERMINAL_STATUSES:
            raise RunError(f"Terminal run '{run_id}' cannot be cancelled.")
        return self.transition(run_id, RunStatus.CANCELLED)

    def cancel_for_owner(self, run_id: UUID, requested_by: str) -> RunRecord:
        """Cancel a run only when its persisted owner matches the caller."""
        self.get_for_owner(run_id, requested_by)
        return self.cancel(run_id)


def validate_aoi(geometry: dict, descriptor: ModelDescriptor) -> AoiValidation:
    """Validate an EPSG:4326 AOI against PlanAura's fixed input footprint."""
    try:
        parsed = shape(geometry)
    except (KeyError, TypeError, ValueError) as exc:
        raise RunError("AOI must be valid GeoJSON in EPSG:4326.") from exc
    if parsed.geom_type not in {"Polygon", "MultiPolygon"}:
        raise RunError("AOI must be a Polygon or MultiPolygon.")
    if parsed.is_empty or not parsed.is_valid:
        raise RunError("AOI must be non-empty and topologically valid.")
    min_x, min_y, max_x, max_y = parsed.bounds
    if not (-180 <= min_x <= max_x <= 180 and -90 <= min_y <= max_y <= 90):
        raise RunError("AOI coordinates must be longitude/latitude in EPSG:4326.")

    centroid = parsed.centroid
    zone = min(60, max(1, int((centroid.x + 180) // 6) + 1))
    local_crs = CRS.from_dict(
        {"proj": "utm", "zone": zone, "south": centroid.y < 0, "datum": "WGS84"}
    )
    projector = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    projected = transform(projector.transform, parsed)
    projected_min_x, projected_min_y, projected_max_x, projected_max_y = projected.bounds
    width_m = projected_max_x - projected_min_x
    height_m = projected_max_y - projected_min_y
    maximum_side_m = descriptor.native_resolution_m * descriptor.tile_size_pixels
    if width_m > maximum_side_m or height_m > maximum_side_m:
        raise RunError(
            f"AOI must fit inside PlanAura's {maximum_side_m / 1000:.2f} km square context."
        )
    area_m2, _ = GEOD.geometry_area_perimeter(parsed)
    within_training_envelope = CANADA_ENVELOPE.covers(parsed)
    warnings = () if within_training_envelope else (
        "AOI is outside PlanAura's Canadian training envelope; treat results as indicative.",
    )
    return AoiValidation(
        area_km2=abs(area_m2) / 1_000_000,
        width_m=width_m,
        height_m=height_m,
        within_training_envelope=within_training_envelope,
        warnings=warnings,
    )


def resolve_compatibility(
    descriptor: ModelDescriptor,
    observations: tuple[ImageryObservation, ImageryObservation],
) -> CompatibilityDecision:
    """Resolve pair suitability without reading raster bytes."""
    first, second = observations
    errors: list[str] = []
    warnings: list[str] = []
    if first.item_id == second.item_id:
        errors.append("same_item_for_both_epochs")
    if first.collection != second.collection:
        errors.append("different_collections")
    if first.tile_id and second.tile_id and first.tile_id != second.tile_id:
        errors.append("different_tiles")
    overlap = _footprint_overlap(first.geometry, second.geometry)
    if overlap < 0.95:
        errors.append("insufficient_footprint_overlap")
    day_delta = _cyclic_day_delta(first.acquired_at, second.acquired_at)
    if day_delta > 45:
        errors.append("seasonal_misalignment")

    for observation in observations:
        if observation.collection not in descriptor.supported_collections:
            errors.append(f"unsupported_collection:{observation.item_id}")
            continue
        required_bands = descriptor.band_mapping_by_collection[observation.collection]
        missing = sorted(
            (set(required_bands) | {descriptor.required_quality_asset})
            - observation.asset_keys
        )
        if missing:
            errors.append(f"missing_assets:{observation.item_id}:{','.join(missing)}")
        if not math.isclose(
            observation.resolution_m,
            descriptor.native_resolution_m,
            rel_tol=0.001,
            abs_tol=0.01,
        ):
            errors.append(f"unsupported_resolution:{observation.item_id}")
        if observation.acquired_at.month not in descriptor.preferred_months:
            warnings.append(
                f"{observation.item_id} is outside PlanAura's preferred June-September season."
            )
    if errors:
        return CompatibilityDecision(
            compatible=False,
            errors=tuple(dict.fromkeys(errors)),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    recipe = PreprocessingRecipe(
        collection=first.collection,
        band_assets=descriptor.band_mapping_by_collection[first.collection],
        quality_asset=descriptor.required_quality_asset,
        target_resolution_m=descriptor.native_resolution_m,
        tile_size_pixels=descriptor.tile_size_pixels,
        patch_stride_pixels=descriptor.patch_stride_pixels,
        normalization_mean=descriptor.normalization_mean,
        normalization_std=descriptor.normalization_std,
        source_no_data_value=descriptor.source_no_data_value,
        model_no_data_value=descriptor.model_no_data_value,
        minimum_valid_fraction=descriptor.minimum_valid_fraction,
    )
    return CompatibilityDecision(
        compatible=True,
        warnings=tuple(dict.fromkeys(warnings)),
        recipe=recipe,
    )


def _request_hash(request: CompareEpochsRequest) -> str:
    canonical = json.dumps(
        request.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _cyclic_day_delta(first: datetime, second: datetime) -> int:
    difference = abs(first.timetuple().tm_yday - second.timetuple().tm_yday)
    return min(difference, 366 - difference)


def _footprint_overlap(first: dict, second: dict) -> float:
    first_shape = shape(first)
    second_shape = shape(second)
    denominator = min(first_shape.area, second_shape.area)
    if denominator == 0:
        return 0
    return first_shape.intersection(second_shape).area / denominator