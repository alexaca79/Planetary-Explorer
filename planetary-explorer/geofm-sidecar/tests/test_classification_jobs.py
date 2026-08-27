"""Admission tests for the Sentinel-1/2/3 PlanAura classification profiles."""

from datetime import UTC, datetime

import pytest

from geofm_service.contracts import ClassifyAoiRequest, RunStatus
from geofm_service.jobs import (
    ImageryObservation,
    InMemoryRunRepository,
    RunError,
    RunService,
    resolve_compatibility,
    validate_aoi,
)
from geofm_service.policy import (
    ApprovalState,
    Capability,
    ClassificationMode,
    SensorFamily,
    get_model,
    list_class_schemes,
    list_models,
    supported_collections,
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
WIDE_AOI = {
    "type": "Polygon",
    "coordinates": [
        [
            [-111.9, 56.70],
            [-111.0, 56.70],
            [-111.0, 57.10],
            [-111.9, 57.10],
            [-111.9, 56.70],
        ]
    ],
}
OUTSIDE_AOI = {
    "type": "Polygon",
    "coordinates": [
        [
            [2.35, 48.85],
            [2.36, 48.85],
            [2.36, 48.86],
            [2.35, 48.86],
            [2.35, 48.85],
        ]
    ],
}
S2_BANDS = ("B02", "B03", "B04", "B8A", "B11", "B12")
S2_RESOLUTIONS = {
    "B02": 10.0,
    "B03": 10.0,
    "B04": 10.0,
    "B8A": 20.0,
    "B11": 20.0,
    "B12": 20.0,
    "SCL": 20.0,
}


class RecordingDispatcher:
    """Capture dispatched run identifiers."""

    def __init__(self) -> None:
        self.run_ids: list = []

    def dispatch(self, record) -> None:
        self.run_ids.append(record.run_id)


def _sentinel2(item_id: str = "s2-a", *, month: int = 7, include_scl: bool = True):
    assets = set(S2_BANDS)
    if include_scl:
        assets.add("SCL")
    return ImageryObservation(
        item_id=item_id,
        collection="sentinel-2-l2a",
        asset_keys=frozenset(assets),
        resolution_m=10.0,
        asset_resolutions_m={key: S2_RESOLUTIONS[key] for key in assets},
        acquired_at=datetime(2024, month, 15, tzinfo=UTC),
        tile_id="12VVN",
        geometry=AOI,
    )


def _sentinel1(item_id: str = "s1-a"):
    return ImageryObservation(
        item_id=item_id,
        collection="sentinel-1-rtc",
        asset_keys=frozenset({"vv", "vh", "mask"}),
        resolution_m=10.0,
        asset_resolutions_m={"vv": 10.0, "vh": 10.0, "mask": 10.0},
        acquired_at=datetime(2024, 7, 15, tzinfo=UTC),
        geometry=AOI,
    )


def _classify_request(
    profile: str = "planaura_classify_s2",
    *,
    item_ids: tuple[str, ...] = ("s2-a",),
    class_scheme: str = "planaura_unsupervised_v1",
    geometry: dict | None = None,
    max_classes: int = 6,
) -> ClassifyAoiRequest:
    return ClassifyAoiRequest(
        geometry=geometry or AOI,
        item_ids=list(item_ids),
        profile=profile,
        class_scheme=class_scheme,
        correlation_id="turn-1",
        requested_by="session-1",
        max_classes=max_classes,
    )


def _service(
    observations: dict,
    *,
    allow_conditional: bool = True,
    max_active: int = 3,
) -> tuple[RunService, RecordingDispatcher]:
    dispatcher = RecordingDispatcher()
    service = RunService(
        InMemoryRunRepository(),
        dispatcher,
        inventory_lookup=observations.__getitem__,
        allow_conditional_models=allow_conditional,
        max_active_runs_per_owner=max_active,
    )
    return service, dispatcher


def test_given_registry_when_listing_then_every_profile_is_pinned_and_gated():
    # Arrange / Act
    descriptors = list_models()

    # Assert
    assert {descriptor.profile.value for descriptor in descriptors} == {
        "planaura_hls",
        "planaura_classify_s2",
        "planaura_classify_s1",
        "planaura_classify_s3",
    }
    for descriptor in descriptors:
        assert len(descriptor.checkpoint_sha256) == 64
        assert descriptor.checkpoint_size_bytes > 0
        assert descriptor.required_attribution
        if descriptor.capability is Capability.CLASSIFY:
            assert descriptor.class_scheme_id
            assert descriptor.classification_mode is ClassificationMode.UNSUPERVISED
            assert descriptor.mandatory_warnings


@pytest.mark.parametrize(
    ("profile", "state"),
    [
        ("planaura_classify_s2", ApprovalState.CONDITIONAL),
        ("planaura_classify_s1", ApprovalState.BLOCKED),
        ("planaura_classify_s3", ApprovalState.BLOCKED),
    ],
)
def test_given_classification_profile_when_resolved_then_approval_state_is_pinned(
    profile,
    state,
):
    # Arrange / Act
    descriptor = get_model(profile)

    # Assert
    assert descriptor.approval_state is state


def test_given_unknown_profile_when_resolved_then_registry_fails_closed():
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="Unsupported GeoFM profile"):
        get_model("planaura_classify_s9")


def test_given_registry_when_listing_collections_then_only_supported_are_returned():
    # Arrange / Act
    collections = supported_collections()

    # Assert
    assert "sentinel-2-l2a" in collections
    assert "sentinel-1-rtc" in collections
    assert "hls2-s30" in collections
    assert all(isinstance(collection, str) for collection in collections)


def test_given_class_schemes_when_listed_then_labels_and_licences_are_published():
    # Arrange / Act
    schemes = list_class_schemes()

    # Assert
    assert schemes
    for scheme in schemes:
        assert scheme.license
        assert scheme.source
        assert len(scheme.labels) >= 2
        assert len({label.value for label in scheme.labels}) == len(scheme.labels)


def test_given_sentinel2_scene_when_resolving_then_run_is_compatible_with_warnings():
    # Arrange
    descriptor = get_model("planaura_classify_s2")

    # Act
    decision = resolve_compatibility(descriptor, [_sentinel2()], _classify_request())

    # Assert
    assert decision.compatible
    assert decision.recipe is not None
    assert decision.recipe.capability is Capability.CLASSIFY
    assert decision.recipe.sensor_family is SensorFamily.OPTICAL
    assert decision.recipe.class_scheme_id == "planaura_unsupervised_v1"
    assert decision.recipe.cloud_masking == "sentinel2_scl"
    assert decision.recipe.output_metric == "class_label"
    assert any("unsupervised" in warning for warning in decision.warnings)


def test_given_missing_scl_when_resolving_then_missing_assets_is_reported():
    # Arrange
    descriptor = get_model("planaura_classify_s2")

    # Act
    decision = resolve_compatibility(
        descriptor,
        [_sentinel2(include_scl=False)],
        _classify_request(),
    )

    # Assert
    assert not decision.compatible
    assert any(error.startswith("missing_assets:") for error in decision.errors)


def test_given_out_of_season_scene_when_resolving_then_season_warning_is_emitted():
    # Arrange
    descriptor = get_model("planaura_classify_s2")

    # Act
    decision = resolve_compatibility(
        descriptor,
        [_sentinel2(month=1)],
        _classify_request(),
    )

    # Assert
    assert decision.compatible
    assert any("June-September" in warning for warning in decision.warnings)


def test_given_wrong_collection_when_resolving_then_unsupported_collection_is_reported():
    # Arrange
    descriptor = get_model("planaura_classify_s2")

    # Act
    decision = resolve_compatibility(descriptor, [_sentinel1()], _classify_request())

    # Assert
    assert not decision.compatible
    assert any(error.startswith("unsupported_collection:") for error in decision.errors)


def test_given_sar_scene_alone_when_resolving_then_fusion_scene_is_required():
    # Arrange
    descriptor = get_model("planaura_classify_s1")

    # Act
    decision = resolve_compatibility(
        descriptor,
        [_sentinel1()],
        _classify_request("planaura_classify_s1"),
    )

    # Assert
    assert not decision.compatible
    assert "fusion_scene_required" in decision.errors


def test_given_sar_and_optical_scenes_when_resolving_then_fusion_recipe_is_built():
    # Arrange
    descriptor = get_model("planaura_classify_s1")

    # Act
    decision = resolve_compatibility(
        descriptor,
        [_sentinel1(), _sentinel2()],
        _classify_request("planaura_classify_s1"),
    )

    # Assert
    assert decision.compatible
    assert decision.recipe is not None
    assert decision.recipe.sensor_family is SensorFamily.SAR
    assert decision.recipe.fusion_collection == "sentinel-2-l2a"
    assert decision.recipe.fusion_band_assets == S2_BANDS
    assert decision.recipe.band_semantics == ("VV", "VH")
    assert any("backscatter" in warning for warning in decision.warnings)


def test_given_sentinel3_profile_when_resolving_then_coarse_warning_is_unconditional():
    # Arrange
    descriptor = get_model("planaura_classify_s3")
    observation = ImageryObservation(
        item_id="s3-a",
        collection="sentinel-3-olci-wfr-l2-netcdf",
        asset_keys=frozenset(
            {
                "oa04-reflectance",
                "oa06-reflectance",
                "oa08-reflectance",
                "oa17-reflectance",
                "wqsf",
            }
        ),
        resolution_m=300.0,
        acquired_at=datetime(2024, 7, 15, tzinfo=UTC),
        geometry=AOI,
    )

    # Act
    decision = resolve_compatibility(
        descriptor,
        [observation],
        _classify_request("planaura_classify_s3", class_scheme="planaura_coarse_regime_v1"),
    )

    # Assert
    assert decision.compatible
    assert any("300 m or coarser" in warning for warning in decision.warnings)


def test_given_no_scene_when_resolving_classification_then_source_is_required():
    # Arrange
    descriptor = get_model("planaura_classify_s2")

    # Act
    decision = resolve_compatibility(descriptor, [], _classify_request())

    # Assert
    assert not decision.compatible
    assert "source_scene_required" in decision.errors


@pytest.mark.parametrize(
    ("profile", "expected_km"),
    [
        ("planaura_classify_s2", 15.36),
        ("planaura_classify_s1", 5.12),
        ("planaura_classify_s3", 153.6),
    ],
)
def test_given_profile_when_validating_aoi_then_cap_derives_from_profile(
    profile,
    expected_km,
):
    # Arrange
    descriptor = get_model(profile)

    # Act
    validation = validate_aoi(AOI, descriptor)

    # Assert
    assert validation.width_m <= descriptor.native_resolution_m * descriptor.tile_size_pixels
    assert round(descriptor.native_resolution_m * descriptor.tile_size_pixels / 1000, 2) == (
        expected_km
    )


def test_given_oversized_aoi_when_validating_then_profile_cap_is_enforced():
    # Arrange
    descriptor = get_model("planaura_classify_s2")

    # Act / Assert
    with pytest.raises(RunError, match=r"planaura_classify_s2 15\.36 km square context"):
        validate_aoi(WIDE_AOI, descriptor)


def test_given_aoi_outside_scope_when_validating_then_envelope_warning_is_emitted():
    # Arrange
    descriptor = get_model("planaura_classify_s2")

    # Act
    validation = validate_aoi(OUTSIDE_AOI, descriptor)

    # Assert
    assert not validation.within_training_envelope
    assert any("Canada training" in warning for warning in validation.warnings)


def test_given_classification_request_when_submitted_then_run_is_queued_with_warnings():
    # Arrange
    service, dispatcher = _service({"s2-a": _sentinel2()})

    # Act
    record, created = service.submit(_classify_request())

    # Assert
    assert created
    assert record.status is RunStatus.QUEUED
    assert dispatcher.run_ids == [record.run_id]
    assert record.preprocessing_recipe["class_scheme_id"] == "planaura_unsupervised_v1"
    assert any("unsupervised" in warning for warning in record.warnings)


def test_given_identical_classification_request_when_resubmitted_then_run_is_reused():
    # Arrange
    service, _ = _service({"s2-a": _sentinel2()})
    first, _ = service.submit(_classify_request())

    # Act
    second, created = service.submit(_classify_request())

    # Assert
    assert not created
    assert second.run_id == first.run_id


def test_given_blocked_profile_when_submitted_then_admission_fails_closed():
    # Arrange
    service, _ = _service({"s1-a": _sentinel1(), "s2-a": _sentinel2()})

    # Act / Assert
    with pytest.raises(RunError, match="is blocked"):
        service.submit(
            _classify_request(
                "planaura_classify_s1",
                item_ids=("s1-a", "s2-a"),
                class_scheme="planaura_sar_surface_v1",
            )
        )


def test_given_conditional_profile_without_approval_then_admission_fails_closed():
    # Arrange
    service, _ = _service({"s2-a": _sentinel2()}, allow_conditional=False)

    # Act / Assert
    with pytest.raises(RunError, match="requires explicit deployment approval"):
        service.submit(_classify_request())


def test_given_change_profile_when_classifying_then_capability_mismatch_is_rejected():
    # Arrange
    service, _ = _service({"s2-a": _sentinel2()})

    # Act / Assert
    with pytest.raises(RunError, match="cannot perform 'classify' work"):
        service.submit(_classify_request("planaura_hls"))


def test_given_foreign_class_scheme_when_submitted_then_scheme_binding_is_enforced():
    # Arrange
    service, _ = _service({"s2-a": _sentinel2()})

    # Act / Assert
    with pytest.raises(RunError, match="publishes class scheme"):
        service.submit(_classify_request(class_scheme="planaura_coarse_regime_v1"))


def test_given_more_classes_than_scheme_publishes_then_request_is_rejected():
    # Arrange
    service, _ = _service({"s2-a": _sentinel2()})

    # Act / Assert
    with pytest.raises(RunError, match="publishes 6 classes"):
        service.submit(_classify_request(max_classes=12))


def test_given_aoi_outside_scene_footprint_then_coverage_is_enforced():
    # Arrange
    service, _ = _service({"s2-a": _sentinel2()})

    # Act / Assert
    with pytest.raises(RunError, match="not fully covered"):
        service.submit(_classify_request(geometry=OUTSIDE_AOI))


def test_given_owner_at_quota_when_submitting_then_concurrency_cap_is_enforced():
    # Arrange
    service, _ = _service(
        {f"s2-{index}": _sentinel2(f"s2-{index}") for index in range(3)},
        max_active=2,
    )
    service.submit(_classify_request(item_ids=("s2-0",)))
    service.submit(_classify_request(item_ids=("s2-1",)))

    # Act / Assert
    with pytest.raises(RunError, match="Too many active GeoFM runs"):
        service.submit(_classify_request(item_ids=("s2-2",)))


def test_given_owner_at_quota_when_resubmitting_same_request_then_quota_is_exempt():
    # Arrange
    service, _ = _service(
        {f"s2-{index}": _sentinel2(f"s2-{index}") for index in range(2)},
        max_active=1,
    )
    first, _ = service.submit(_classify_request(item_ids=("s2-0",)))

    # Act
    second, created = service.submit(_classify_request(item_ids=("s2-0",)))

    # Assert
    assert not created
    assert second.run_id == first.run_id
