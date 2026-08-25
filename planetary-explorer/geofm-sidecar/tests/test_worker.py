"""Model-free geospatial reduction tests for the PlanAura worker."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import numpy as np
import pytest
from affine import Affine

from geofm_service.contracts import CompareEpochsRequest, RunRecord
from geofm_service.jobs import PreprocessingRecipe
from geofm_service.policy import PLAN_AURA_HLS
from geofm_service.stac import StacItemSummary
from geofm_service.worker import (
    WorkerError,
    build_evidence_manifest,
    build_fixed_grid,
    consume_one_message,
    sanitize_error,
    summarize_distance,
    valid_hls_fmask,
    validate_asset_url,
    vectorize_distance,
)

AOI = {
    "type": "Polygon",
    "coordinates": [
        [
            [-111.35, 56.70],
            [-111.34, 56.70],
            [-111.34, 56.71],
            [-111.35, 56.71],
            [-111.35, 56.70],
        ]
    ],
}


def test_given_hls_quality_flags_when_masking_then_contaminated_pixels_are_rejected() -> None:
    # Arrange
    quality = np.array([0, 1, 2, 4, 8, 16, 32, 192], dtype=np.uint8)

    # Act
    valid = valid_hls_fmask(quality)

    # Assert
    assert valid.tolist() == [True, False, False, False, False, False, True, False]


def test_given_small_aoi_when_building_grid_then_native_dimensions_are_fixed() -> None:
    # Act
    transform_value, mask = build_fixed_grid(
        "EPSG:32612",
        AOI,
        resolution_m=30,
        tile_size_pixels=512,
    )

    # Assert
    assert transform_value.a == 30
    assert transform_value.e == -30
    assert mask.shape == (512, 512)
    assert mask.any()


def test_given_distance_region_when_vectorizing_then_ranked_geojson_is_returned() -> None:
    # Arrange
    values = np.full((8, 8), np.nan, dtype=np.float32)
    values[2:6, 2:6] = 0.8

    # Act
    features = vectorize_distance(
        values,
        transform_value=Affine(30, 0, 500000, 0, -30, 6300000),
        crs="EPSG:32612",
        threshold=0.35,
        max_features=10,
    )

    # Assert
    assert len(features) == 1
    assert features[0]["type"] == "Feature"
    assert features[0]["properties"]["rank"] == 1
    assert features[0]["properties"]["mean_distance"] == pytest.approx(0.8)


def test_given_fragmented_distance_when_vectorizing_then_expensive_masks_are_capped(
    monkeypatch,
) -> None:
    # Arrange
    import geofm_service.worker as worker_module

    values = np.full((12, 12), np.nan, dtype=np.float32)
    values[::3, ::3] = 0.8
    mask_calls = 0
    real_geometry_mask = worker_module.geometry_mask

    def counting_geometry_mask(*args, **kwargs):
        nonlocal mask_calls
        mask_calls += 1
        return real_geometry_mask(*args, **kwargs)

    monkeypatch.setattr(worker_module, "geometry_mask", counting_geometry_mask)

    # Act
    features = vectorize_distance(
        values,
        transform_value=Affine(30, 0, 500000, 0, -30, 6300000),
        crs="EPSG:32612",
        threshold=0.35,
        max_features=3,
    )

    # Assert
    assert len(features) == 3
    assert mask_calls == 3


def test_given_boundary_pixel_when_vectorizing_then_geometry_is_clipped_to_aoi() -> None:
    # Arrange
    values = np.array([[0.8]], dtype=np.float32)
    clip_geometry = {
        "type": "Polygon",
        "coordinates": [
            [[0.0, 0.0], [0.5, 0.0], [0.5, 1.0], [0.0, 1.0], [0.0, 0.0]]
        ],
    }

    # Act
    features = vectorize_distance(
        values,
        transform_value=Affine(1, 0, 0, 0, -1, 1),
        crs="EPSG:4326",
        threshold=0.35,
        max_features=1,
        clip_geometry=clip_geometry,
    )

    # Assert
    coordinates = features[0]["geometry"]["coordinates"][0]
    assert max(point[0] for point in coordinates) <= 0.5


def test_given_valid_distance_when_summarizing_then_all_measurements_are_scalar() -> None:
    # Arrange
    values = np.array([[0.1, 0.5], [np.nan, 0.9]], dtype=np.float32)

    # Act
    statistics = summarize_distance(
        values,
        transform_value=Affine(30, 0, 500000, 0, -30, 6300000),
        threshold=0.35,
    )

    # Assert
    assert statistics["valid_pixel_count"] == 3
    assert statistics["changed_pixel_count"] == 2
    assert statistics["changed_area_km2"] == pytest.approx(0.0018)
    assert statistics["maximum_distance"] == pytest.approx(0.9)


def test_given_capped_vectors_when_summarizing_then_changed_area_uses_all_pixels() -> None:
    # Arrange
    values = np.full((10, 10), 0.8, dtype=np.float32)

    # Act
    statistics = summarize_distance(
        values,
        transform_value=Affine(30, 0, 500000, 0, -30, 6300000),
        threshold=0.35,
    )

    # Assert
    assert statistics["changed_pixel_count"] == 100
    assert statistics["changed_area_km2"] == pytest.approx(0.09)


def test_given_unsigned_or_unapproved_asset_url_when_validating_then_it_is_rejected() -> None:
    # Act & Assert
    with pytest.raises(WorkerError, match="approved blob host"):
        validate_asset_url("https://example.com/image.tif?sig=test")
    with pytest.raises(WorkerError, match="short-lived signature"):
        validate_asset_url("https://example.blob.core.windows.net/hls/image.tif")


def test_given_signed_url_in_error_when_sanitizing_then_query_is_redacted() -> None:
    # Arrange
    error = RuntimeError(
        "failed https://example.blob.core.windows.net/hls/image.tif?sig=secret&se=tomorrow"
    )

    # Act
    sanitized = sanitize_error(error)

    # Assert
    assert "secret" not in sanitized
    assert sanitized.endswith("?<redacted>")


def test_given_outputs_when_building_manifest_then_hashes_and_model_pin_are_recorded(
    tmp_path: Path,
) -> None:
    # Arrange
    output = tmp_path / "change_distance.tif"
    output.write_bytes(b"derived raster")
    request = CompareEpochsRequest(
        geometry=AOI,
        item_id_epoch_a="epoch-a",
        item_id_epoch_b="epoch-b",
        correlation_id="turn-1",
        requested_by="session-1",
    )
    recipe = PreprocessingRecipe(
        collection="hls2-s30",
        band_assets=("B02", "B03", "B04", "B8A", "B11", "B12"),
        quality_asset="Fmask",
        target_resolution_m=30,
        tile_size_pixels=512,
        patch_stride_pixels=16,
        normalization_mean=PLAN_AURA_HLS.normalization_mean,
        normalization_std=PLAN_AURA_HLS.normalization_std,
        source_no_data_value=-9999,
        model_no_data_value=0.0001,
        minimum_valid_fraction=0.7,
    )
    record = RunRecord(
        idempotency_key="0" * 64,
        request=request,
        selected_model=PLAN_AURA_HLS.model_dump(mode="json"),
        preprocessing_recipe=recipe.model_dump(mode="json"),
    )
    item = StacItemSummary(
        item_id="epoch-a",
        collection="hls2-s30",
        acquired_at=datetime(2023, 7, 15, tzinfo=UTC),
        geometry=AOI,
        bbox=(-111.35, 56.70, -111.34, 56.71),
    )
    generated_at = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)

    # Act
    manifest = build_evidence_manifest(
        record,
        item,
        StacItemSummary(
            item_id="epoch-b",
            collection="hls2-s30",
            acquired_at=datetime(2024, 7, 15, tzinfo=UTC),
            geometry=AOI,
            bbox=(-111.35, 56.70, -111.34, 56.71),
        ),
        {"mean_feature_distance": 0.2},
        {"change_distance": output},
        generated_at=generated_at,
    )

    # Assert
    assert manifest["run"]["updated_at"] == generated_at.isoformat()
    assert manifest["model"]["checkpoint_sha256"] == PLAN_AURA_HLS.checkpoint_sha256
    assert manifest["outputs"] == [
        {
            "kind": "change_distance",
            "filename": "change_distance.tif",
            "size_bytes": 14,
            "sha256": hashlib.sha256(b"derived raster").hexdigest(),
        }
    ]


def test_given_run_load_failure_when_consuming_then_queue_message_is_not_deleted() -> None:
    # Arrange
    class Message:
        content = '{"run_id":"00000000-0000-0000-0000-000000000001"}'

    class Queue:
        def __init__(self) -> None:
            self.deleted = False

        def receive_messages(self, **_kwargs):
            return [Message()]

        def delete_message(self, _message) -> None:
            self.deleted = True

    class FailingService:
        def get(self, _run_id):
            raise RuntimeError(
                "storage failed https://example.blob.core.windows.net/geofm/run?sig=secret"
            )

    queue = Queue()

    # Act
    consumed = consume_one_message(queue, FailingService(), container=None)

    # Assert
    assert consumed is True
    assert queue.deleted is False


def test_given_malformed_message_when_consuming_then_message_is_deleted() -> None:
    # Arrange
    class Message:
        content = "not-json"
        dequeue_count = 1

    class Queue:
        def __init__(self) -> None:
            self.deleted = False

        def receive_messages(self, **_kwargs):
            return [Message()]

        def delete_message(self, _message) -> None:
            self.deleted = True

    queue = Queue()

    # Act
    consumed = consume_one_message(queue, service=None, container=None)

    # Assert
    assert consumed is True
    assert queue.deleted is True


def test_given_storage_outage_when_retry_limit_reached_then_message_is_retained(
    monkeypatch,
) -> None:
    # Arrange
    class Message:
        content = '{"run_id":"00000000-0000-0000-0000-000000000001"}'
        dequeue_count = 5

    class Queue:
        def __init__(self) -> None:
            self.deleted = False

        def receive_messages(self, **_kwargs):
            return [Message()]

        def delete_message(self, _message) -> None:
            self.deleted = True

    class FailingService:
        def get(self, _run_id):
            raise RuntimeError("storage unavailable")

    monkeypatch.setenv("GEOFM_MAX_DEQUEUE_COUNT", "5")
    queue = Queue()

    # Act
    consume_one_message(queue, FailingService(), container=None)

    # Assert
    assert queue.deleted is False


@pytest.mark.parametrize("processing_error", [KeyError("field"), ValueError("shape")])
def test_given_parse_like_processing_failure_when_consuming_then_run_is_failed_before_delete(
    monkeypatch,
    processing_error: Exception,
) -> None:
    # Arrange
    from unittest.mock import MagicMock

    import geofm_service.worker as worker_module
    from geofm_service.contracts import RunStatus

    class Message:
        content = '{"run_id":"00000000-0000-0000-0000-000000000001"}'
        dequeue_count = 1

    class Queue:
        def __init__(self) -> None:
            self.deleted = False

        def receive_messages(self, **_kwargs):
            return [Message()]

        def delete_message(self, _message) -> None:
            self.deleted = True

    record = MagicMock()
    record.status = RunStatus.RUNNING
    record.run_id = UUID("00000000-0000-0000-0000-000000000001")
    service = MagicMock()
    service.get.return_value = record
    monkeypatch.setattr(
        worker_module,
        "process_run",
        MagicMock(side_effect=processing_error),
    )
    queue = Queue()

    # Act
    consume_one_message(queue, service, container="container")

    # Assert
    service.transition.assert_called_once_with(
        record.run_id,
        RunStatus.FAILED,
        error=sanitize_error(processing_error),
    )
    assert queue.deleted is True


def test_given_redelivered_running_run_when_consuming_then_processing_restarts(
    monkeypatch,
) -> None:
    # Arrange
    from unittest.mock import MagicMock

    import geofm_service.worker as worker_module
    from geofm_service.contracts import RunStatus

    class Message:
        content = '{"run_id":"00000000-0000-0000-0000-000000000001"}'

    class Queue:
        def __init__(self) -> None:
            self.deleted = False

        def receive_messages(self, **_kwargs):
            return [Message()]

        def delete_message(self, _message) -> None:
            self.deleted = True

    record = MagicMock()
    record.status = RunStatus.RUNNING
    service = MagicMock()
    service.get.return_value = record
    process = MagicMock()
    monkeypatch.setattr(worker_module, "process_run", process)
    queue = Queue()

    # Act
    consume_one_message(queue, service, container="container")

    # Assert
    process.assert_called_once_with(record, service, "container")
    assert queue.deleted is True


def test_given_missing_run_when_retry_limit_reached_then_message_is_deleted(
    monkeypatch,
) -> None:
    # Arrange
    from geofm_service.jobs import RunError

    class Message:
        content = '{"run_id":"00000000-0000-0000-0000-000000000001"}'
        dequeue_count = 5

    class Queue:
        def __init__(self) -> None:
            self.deleted = False

        def receive_messages(self, **_kwargs):
            return [Message()]

        def delete_message(self, _message) -> None:
            self.deleted = True

    class MissingRunService:
        def get(self, _run_id):
            raise RunError("Run was not found.")

    monkeypatch.setenv("GEOFM_MAX_DEQUEUE_COUNT", "5")
    queue = Queue()

    # Act
    consume_one_message(queue, MissingRunService(), container=None)

    # Assert
    assert queue.deleted is True