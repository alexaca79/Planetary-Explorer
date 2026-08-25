"""Admission, idempotency, and lifecycle tests for GeoFM runs."""

from datetime import UTC, datetime

import pytest
from azure.core.exceptions import ResourceModifiedError

from geofm_service.contracts import CompareEpochsRequest, RunStatus
from geofm_service.jobs import (
    BlobRunRepository,
    ImageryObservation,
    InMemoryRunRepository,
    RunError,
    RunService,
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


class RecordingDispatcher:
    """Capture dispatched run identifiers."""

    def __init__(self) -> None:
        self.run_ids = []

    def dispatch(self, record) -> None:
        self.run_ids.append(record.run_id)


class FailOnceDispatcher(RecordingDispatcher):
    """Fail the first dispatch and record subsequent redrives."""

    def __init__(self) -> None:
        super().__init__()
        self._failed = False

    def dispatch(self, record) -> None:
        if not self._failed:
            self._failed = True
            raise RuntimeError("queue unavailable")
        super().dispatch(record)


def _observation(item_id: str, year: int, *, include_fmask: bool = True):
    assets = {"B02", "B03", "B04", "B8A", "B11", "B12"}
    if include_fmask:
        assets.add("Fmask")
    return ImageryObservation(
        item_id=item_id,
        collection="hls2-s30",
        asset_keys=frozenset(assets),
        resolution_m=30,
        acquired_at=datetime(year, 7, 15, tzinfo=UTC),
        tile_id="15VUC",
        geometry=AOI,
    )


def _request() -> CompareEpochsRequest:
    return CompareEpochsRequest(
        geometry=AOI,
        item_id_epoch_a="epoch-a",
        item_id_epoch_b="epoch-b",
        correlation_id="turn-1",
        requested_by="session-1",
    )


def test_given_conditional_model_without_approval_when_submitting_then_it_fails_closed() -> None:
    # Arrange
    service = RunService(
        InMemoryRunRepository(),
        RecordingDispatcher(),
        inventory_lookup=lambda item_id: _observation(item_id, 2023),
    )

    # Act & Assert
    with pytest.raises(RunError, match="explicit deployment approval"):
        service.submit(_request())


def test_given_missing_fmask_when_submitting_then_admission_rejects_the_pair() -> None:
    # Arrange
    service = RunService(
        InMemoryRunRepository(),
        RecordingDispatcher(),
        inventory_lookup=lambda item_id: _observation(
            item_id,
            2023 if item_id == "epoch-a" else 2024,
            include_fmask=item_id != "epoch-b",
        ),
        allow_conditional_models=True,
    )

    # Act & Assert
    with pytest.raises(RunError, match="missing_assets:epoch-b:Fmask"):
        service.submit(_request())


def test_given_queued_request_twice_when_submitting_then_second_call_redrives_it() -> None:
    # Arrange
    dispatcher = RecordingDispatcher()
    repository = InMemoryRunRepository()
    service = RunService(
        repository,
        dispatcher,
        inventory_lookup=lambda item_id: _observation(
            item_id,
            2023 if item_id == "epoch-a" else 2024,
        ),
        allow_conditional_models=True,
    )

    # Act
    first, first_created = service.submit(_request())
    second, second_created = service.submit(_request())

    # Assert
    assert first_created is True
    assert second_created is False
    assert first.run_id == second.run_id
    assert dispatcher.run_ids == [first.run_id, first.run_id]


def test_given_dispatch_failure_when_resubmitting_then_same_queued_run_is_redriven() -> None:
    # Arrange
    dispatcher = FailOnceDispatcher()
    repository = InMemoryRunRepository()
    service = RunService(
        repository,
        dispatcher,
        inventory_lookup=lambda item_id: _observation(
            item_id,
            2023 if item_id == "epoch-a" else 2024,
        ),
        allow_conditional_models=True,
    )

    # Act
    with pytest.raises(RunError, match="queue dispatch failed"):
        service.submit(_request())
    recovered, created = service.submit(_request())

    # Assert
    assert created is False
    assert recovered.status is RunStatus.QUEUED
    assert dispatcher.run_ids == [recovered.run_id]


def test_given_running_run_when_progress_updates_then_same_state_is_allowed() -> None:
    # Arrange
    service = RunService(
        InMemoryRunRepository(),
        RecordingDispatcher(),
        inventory_lookup=lambda item_id: _observation(
            item_id,
            2023 if item_id == "epoch-a" else 2024,
        ),
        allow_conditional_models=True,
    )
    record, _ = service.submit(_request())
    service.transition(record.run_id, RunStatus.RUNNING, progress_pct=5)

    # Act
    updated = service.transition(record.run_id, RunStatus.RUNNING, progress_pct=45)

    # Assert
    assert updated.progress_pct == 45


def test_given_aoi_larger_than_model_context_when_submitting_then_it_is_rejected() -> None:
    # Arrange
    large_request = _request().model_copy(
        update={
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-111.5, 56.6],
                        [-111.1, 56.6],
                        [-111.1, 57.0],
                        [-111.5, 57.0],
                        [-111.5, 56.6],
                    ]
                ],
            }
        }
    )
    service = RunService(
        InMemoryRunRepository(),
        RecordingDispatcher(),
        inventory_lookup=lambda item_id: _observation(item_id, 2023),
        allow_conditional_models=True,
    )

    # Act & Assert
    with pytest.raises(RunError, match=r"15\.36 km square context"):
        service.submit(large_request)


def test_given_different_owner_when_reading_or_cancelling_then_run_is_hidden() -> None:
    # Arrange
    service = RunService(
        InMemoryRunRepository(),
        RecordingDispatcher(),
        inventory_lookup=lambda item_id: _observation(
            item_id,
            2023 if item_id == "epoch-a" else 2024,
        ),
        allow_conditional_models=True,
    )
    record, _ = service.submit(_request())

    # Act & Assert
    with pytest.raises(RunError, match="was not found"):
        service.get_for_owner(record.run_id, "different-owner")
    with pytest.raises(RunError, match="was not found"):
        service.cancel_for_owner(record.run_id, "different-owner")


def test_given_stale_version_when_saving_then_concurrent_change_is_rejected() -> None:
    # Arrange
    repository = InMemoryRunRepository()
    service = RunService(
        repository,
        RecordingDispatcher(),
        inventory_lookup=lambda item_id: _observation(
            item_id,
            2023 if item_id == "epoch-a" else 2024,
        ),
        allow_conditional_models=True,
    )
    record, _ = service.submit(_request())
    first_copy = repository.get(record.run_id)
    second_copy = repository.get(record.run_id)
    assert first_copy is not None and second_copy is not None
    first_copy.version = 1
    repository.save(first_copy, expected_version=0)
    second_copy.version = 1

    # Act & Assert
    from geofm_service.jobs import RunConflict

    with pytest.raises(RunConflict, match="changed concurrently"):
        repository.save(second_copy, expected_version=0)


def test_given_stale_blob_version_when_saving_then_old_etag_is_rejected() -> None:
    # Arrange
    service = RunService(
        InMemoryRunRepository(),
        RecordingDispatcher(),
        inventory_lookup=lambda item_id: _observation(
            item_id,
            2023 if item_id == "epoch-a" else 2024,
        ),
        allow_conditional_models=True,
    )
    record, _ = service.submit(_request())

    class Download:
        def __init__(self, blob) -> None:
            self._blob = blob
            self.properties = {"etag": blob.etag}

        def readall(self):
            return self._blob.content

    class Blob:
        def __init__(self) -> None:
            self.content = record.model_dump_json()
            self.generation = 0
            self.etag = '"0"'

        def download_blob(self):
            return Download(self)

        def upload_blob(self, content, *, etag, **_kwargs):
            if etag != self.etag:
                raise ResourceModifiedError("condition failed")
            self.content = content
            self.generation += 1
            self.etag = f'"{self.generation}"'
            return {"etag": self.etag}

    class Container:
        def __init__(self) -> None:
            self.blob = Blob()

        def get_blob_client(self, _name):
            return self.blob

    repository = BlobRunRepository(Container())
    first_copy = repository.get(record.run_id)
    second_copy = repository.get(record.run_id)
    assert first_copy is not None and second_copy is not None
    first_copy.version = 1
    repository.save(first_copy, expected_version=0)
    second_copy.version = 1

    # Act & Assert
    from geofm_service.jobs import RunConflict

    with pytest.raises(RunConflict, match="changed concurrently"):
        repository.save(second_copy, expected_version=0)