"""Model-free reduction tests for the PlanAura classification worker."""

import json
from pathlib import Path

import numpy as np
import pytest
from affine import Affine

from geofm_service.contracts import ClassifyAoiRequest, RunRecord
from geofm_service.jobs import PreprocessingRecipe
from geofm_service.policy import (
    UNSUPERVISED_CLUSTER_SCHEME,
    get_class_scheme,
    get_model,
)
from geofm_service.worker import (
    CLASSIFICATION_SEED,
    WorkerError,
    _apply_class_values,
    _nearest_upsample,
    _write_class_map,
    build_evidence_manifest,
    cluster_embeddings,
    name_clusters,
    quality_mask,
    sar_feature_stack,
    spectral_signatures,
    summarize_classes,
    valid_hls_fmask,
    valid_sentinel1_rtc_mask,
    valid_sentinel2_scl,
    valid_sentinel3_flags,
    vectorize_classes,
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
TRANSFORM = Affine(30.0, 0.0, 500_000.0, 0.0, -30.0, 6_300_000.0)
SEMANTICS = ("BLUE", "GREEN", "RED", "NIR_NARROW", "SWIR_1", "SWIR_2")


class _PreparedStub:
    """Minimal stand-in carrying only what the raster writer reads."""

    def __init__(self, crs: str = "EPSG:32612") -> None:
        self.crs = crs
        self.transform = TRANSFORM


def _classify_record() -> RunRecord:
    descriptor = get_model("planaura_classify_s2")
    request = ClassifyAoiRequest(
        geometry=AOI,
        item_ids=["s2-a"],
        profile="planaura_classify_s2",
        class_scheme="planaura_unsupervised_v1",
        correlation_id="turn-1",
        requested_by="session-1",
    )
    recipe = PreprocessingRecipe(
        collection="sentinel-2-l2a",
        band_assets=("B02", "B03", "B04", "B8A", "B11", "B12"),
        quality_asset="SCL",
        target_resolution_m=30.0,
        tile_size_pixels=512,
        patch_stride_pixels=16,
        normalization_mean=descriptor.normalization_mean,
        normalization_std=descriptor.normalization_std,
        source_no_data_value=-9999,
        model_no_data_value=0.0001,
        minimum_valid_fraction=0.7,
        cloud_masking="sentinel2_scl",
        output_metric="class_label",
        class_scheme_id="planaura_unsupervised_v1",
        classification_mode="unsupervised",
    )
    return RunRecord(
        idempotency_key="a" * 64,
        request=request,
        selected_model=descriptor.model_dump(mode="json"),
        preprocessing_recipe=recipe.model_dump(mode="json"),
        warnings=list(descriptor.mandatory_warnings),
    )


def test_given_sentinel2_scl_when_masking_then_only_usable_classes_survive():
    # Arrange
    values = np.array([[0, 3, 4, 5], [6, 7, 8, 9], [10, 11, 1, 2]], dtype=np.uint32)

    # Act
    mask = valid_sentinel2_scl(values)

    # Assert
    assert mask.tolist() == [
        [False, False, True, True],
        [True, True, False, False],
        [False, True, False, False],
    ]


def test_given_sentinel1_rtc_mask_when_masking_then_only_valid_flag_survives():
    # Arrange
    values = np.array([[0, 1, 2, 255]], dtype=np.uint32)

    # Act / Assert
    assert valid_sentinel1_rtc_mask(values).tolist() == [[False, True, False, False]]


def test_given_sentinel3_flags_when_masking_then_flagged_pixels_are_dropped():
    # Arrange
    values = np.array([[0b0, 0b1, 0b10, 0b1_0000_0000]], dtype=np.uint32)

    # Act / Assert
    assert valid_sentinel3_flags(values).tolist() == [[True, False, False, False]]


def test_given_unknown_strategy_when_masking_then_worker_fails_closed():
    # Arrange
    values = np.zeros((2, 2), dtype=np.uint32)

    # Act / Assert
    with pytest.raises(WorkerError, match="Unsupported quality mask strategy"):
        quality_mask("sentinel9_magic", values)


def test_given_known_strategies_when_masking_then_each_dispatches():
    # Arrange
    values = np.ones((2, 2), dtype=np.uint32)

    # Act / Assert
    assert quality_mask("hls_fmask", values.astype(np.uint8)).shape == (2, 2)
    assert quality_mask("sentinel2_scl", values * 4).all()
    assert quality_mask("sentinel1_rtc_mask", values).all()
    assert quality_mask("sentinel3_quality_flags", values * 0).all()
    assert valid_hls_fmask(np.zeros((2, 2), dtype=np.uint8)).all()


def test_given_separable_features_when_clustering_then_labels_are_deterministic():
    # Arrange
    features = np.zeros((2, 8, 8), dtype=np.float32)
    features[0, :, :4] = 10.0
    features[1, :, 4:] = 10.0
    valid = np.ones((8, 8), dtype=bool)

    # Act
    labels, confidence = cluster_embeddings(
        features, valid, max_classes=2, seed=CLASSIFICATION_SEED
    )
    repeat_labels, _ = cluster_embeddings(
        features, valid, max_classes=2, seed=CLASSIFICATION_SEED
    )

    # Assert
    assert np.array_equal(labels, repeat_labels)
    assert set(np.unique(labels).tolist()) == {0, 1}
    assert len(set(labels[:, :4].ravel().tolist())) == 1
    assert len(set(labels[:, 4:].ravel().tolist())) == 1
    assert confidence.min() >= 0.0
    assert confidence.max() <= 1.0


def test_given_masked_pixels_when_clustering_then_they_stay_unlabelled():
    # Arrange
    features = np.random.default_rng(7).normal(size=(3, 6, 6)).astype(np.float32)
    valid = np.ones((6, 6), dtype=bool)
    valid[0, :] = False

    # Act
    labels, confidence = cluster_embeddings(
        features, valid, max_classes=3, seed=CLASSIFICATION_SEED
    )

    # Assert
    assert (labels[0, :] == -1).all()
    assert (confidence[0, :] == 0).all()
    assert (labels[1:, :] >= 0).all()


def test_given_too_few_samples_when_clustering_then_worker_fails_closed():
    # Arrange
    features = np.zeros((2, 2, 2), dtype=np.float32)
    valid = np.zeros((2, 2), dtype=bool)
    valid[0, 0] = True

    # Act / Assert
    with pytest.raises(WorkerError, match="valid samples remain"):
        cluster_embeddings(features, valid, max_classes=4, seed=CLASSIFICATION_SEED)


def test_given_reflectance_when_computing_signatures_then_indices_are_bounded():
    # Arrange
    reflectance = np.stack(
        [np.full((4, 4), value, dtype=np.float32) for value in (100, 300, 200, 900, 400, 150)]
    )

    # Act
    signatures = spectral_signatures(reflectance, SEMANTICS)

    # Assert
    assert set(signatures) >= {"ndvi", "ndwi", "nbr"}
    assert signatures["ndvi"].max() == pytest.approx((900 - 200) / (900 + 200))
    assert signatures["ndwi"].max() == pytest.approx((300 - 900) / (300 + 900))
    assert signatures["nbr"].max() == pytest.approx((900 - 150) / (900 + 150))


def test_given_missing_semantics_when_computing_signatures_then_indices_are_skipped():
    # Arrange
    backscatter = np.stack([np.full((3, 3), 0.2, dtype=np.float32)] * 2)

    # Act
    signatures = spectral_signatures(backscatter, ("VV", "VH"))

    # Assert
    assert "ndvi" not in signatures
    assert "mean_vv" in signatures


def test_given_vegetated_cluster_when_naming_then_a_published_label_is_chosen():
    # Arrange
    labels = np.zeros((4, 4), dtype=np.int64)
    labels[2:, :] = 1
    signatures = {
        "ndvi": np.where(labels == 0, 0.8, -0.4),
        "ndwi": np.where(labels == 0, -0.5, -0.2),
        "nbr": np.where(labels == 0, 0.6, 0.1),
    }
    scheme_labels = tuple(
        label.model_dump(mode="json") for label in UNSUPERVISED_CLUSTER_SCHEME.labels
    )

    # Act
    naming = name_clusters(labels, signatures, scheme_labels)

    # Assert
    published = {label["name"] for label in scheme_labels}
    assert set(naming) == {0, 1}
    assert naming[0]["label"]["name"] in published
    assert naming[1]["label"]["name"] in published
    assert naming[0]["label"]["name"] == "dense_vegetation"
    assert "ndvi" in naming[0]["signature"]


def test_given_named_clusters_when_applying_then_scheme_values_are_written():
    # Arrange
    labels = np.array([[0, 1], [-1, 0]], dtype=np.int64)
    naming = {
        0: {"label": {"value": 1, "name": "dense_vegetation"}},
        1: {"label": {"value": 0, "name": "water"}},
    }

    # Act
    class_map = _apply_class_values(labels, naming, 255)

    # Assert
    assert class_map.dtype == np.uint8
    assert class_map.tolist() == [[1, 0], [255, 1]]


def test_given_class_map_when_summarizing_then_areas_and_confidence_are_reported():
    # Arrange
    class_map = np.array([[1, 1], [0, 255]], dtype=np.uint8)
    confidence = np.array([[0.9, 0.7], [0.5, 0.0]], dtype=np.float32)
    naming = {
        0: {"label": {"value": 1, "name": "dense_vegetation"}},
        1: {"label": {"value": 0, "name": "water"}},
    }

    # Act
    statistics = summarize_classes(
        class_map,
        confidence,
        naming,
        scheme=UNSUPERVISED_CLUSTER_SCHEME,
        transform_value=TRANSFORM,
    )

    # Assert
    assert statistics["class_scheme_id"] == "planaura_unsupervised_v1"
    assert statistics["classified_pixels"] == 3
    assert statistics["unclassified_pixels"] == 1
    by_name = {entry["class_name"]: entry for entry in statistics["classes"]}
    assert by_name["dense_vegetation"]["pixels"] == 2
    assert by_name["dense_vegetation"]["percent_of_classified"] == pytest.approx(66.667)
    assert by_name["dense_vegetation"]["mean_confidence"] == pytest.approx(0.8)
    assert by_name["water"]["area_km2"] == pytest.approx(900 / 1_000_000)


def test_given_class_map_when_vectorizing_then_features_carry_provenance():
    # Arrange
    class_map = np.full((8, 8), 255, dtype=np.uint8)
    class_map[:4, :] = 1
    class_map[4:, :] = 0
    confidence = np.full((8, 8), 0.75, dtype=np.float32)
    naming = {
        0: {"label": {"value": 1, "name": "dense_vegetation"}},
        1: {"label": {"value": 0, "name": "water"}},
    }

    # Act
    features = vectorize_classes(
        class_map,
        confidence,
        naming,
        transform_value=TRANSFORM,
        crs="EPSG:32612",
        scheme=UNSUPERVISED_CLUSTER_SCHEME,
        max_features=5,
    )

    # Assert
    assert features
    for feature in features:
        properties = feature["properties"]
        assert properties["class_scheme_id"] == "planaura_unsupervised_v1"
        assert properties["class_name"] in {"dense_vegetation", "water"}
        assert properties["class_colour"].startswith("#")
        assert properties["mean_confidence"] == pytest.approx(0.75)
        assert properties["area_km2"] > 0


def test_given_zero_budget_when_vectorizing_then_no_features_are_emitted():
    # Arrange
    class_map = np.zeros((4, 4), dtype=np.uint8)
    confidence = np.ones((4, 4), dtype=np.float32)

    # Act
    features = vectorize_classes(
        class_map,
        confidence,
        {0: {"label": {"value": 0, "name": "water"}}},
        transform_value=TRANSFORM,
        crs="EPSG:32612",
        scheme=UNSUPERVISED_CLUSTER_SCHEME,
        max_features=0,
    )

    # Assert
    assert features == []


def test_given_coarse_grid_when_upsampling_then_output_matches_target_shape():
    # Arrange
    values = np.arange(2 * 2 * 2, dtype=np.float32).reshape(2, 2, 2)

    # Act
    upsampled = _nearest_upsample(values, 4, 6)

    # Assert
    assert upsampled.shape == (2, 4, 6)
    assert upsampled[0, 0, 0] == values[0, 0, 0]
    assert upsampled[0, 3, 5] == values[0, 1, 1]


def test_given_rtc_bands_when_building_sar_features_then_stack_is_documented():
    # Arrange
    backscatter = np.stack(
        [np.full((5, 5), 0.4, dtype=np.float32), np.full((5, 5), 0.1, dtype=np.float32)]
    )

    # Act
    stack = sar_feature_stack(backscatter)

    # Assert
    assert stack.shape == (4, 5, 5)
    assert stack[2].max() == pytest.approx(4.0)
    assert np.isfinite(stack).all()


def test_given_single_band_when_building_sar_features_then_worker_fails_closed():
    # Arrange
    backscatter = np.zeros((1, 4, 4), dtype=np.float32)

    # Act / Assert
    with pytest.raises(WorkerError, match="both VV and VH"):
        sar_feature_stack(backscatter)


def test_given_class_map_when_written_then_cog_carries_palette_and_nodata(tmp_path: Path):
    # Arrange
    rasterio = pytest.importorskip("rasterio")
    class_map = np.full((16, 16), 255, dtype=np.uint8)
    class_map[:8, :] = 1
    target = tmp_path / "class_map.tif"

    # Act
    _write_class_map(target, class_map, _PreparedStub(), UNSUPERVISED_CLUSTER_SCHEME)

    # Assert
    with rasterio.open(target) as source:
        assert source.dtypes == ("uint8",)
        assert source.nodata == 255
        assert source.read(1)[0, 0] == 1
        colours = source.colormap(1)
    scheme_colour = get_class_scheme("planaura_unsupervised_v1").labels[1].colour
    assert colours[1][:3] == (
        int(scheme_colour[1:3], 16),
        int(scheme_colour[3:5], 16),
        int(scheme_colour[5:7], 16),
    )


def test_given_classification_run_when_building_manifest_then_provenance_is_complete(
    tmp_path: Path,
):
    # Arrange
    record = _classify_record()
    output = tmp_path / "class_statistics.json"
    output.write_text(json.dumps({"classes": []}), encoding="utf-8")
    from geofm_service.stac import StacItemSummary

    summary = StacItemSummary(
        item_id="s2-a",
        collection="sentinel-2-l2a",
        acquired_at=record.created_at,
        geometry=AOI,
        bbox=(-111.35, 56.70, -111.34, 56.71),
    )

    # Act
    manifest = build_evidence_manifest(
        record,
        summary,
        summary,
        {"class_scheme_id": "planaura_unsupervised_v1"},
        {"class_statistics": output},
        generated_at=record.created_at,
        extra_sources=[summary],
    )

    # Assert
    assert manifest["request"]["kind"] == "classify_aoi"
    assert manifest["class_scheme_id"] == "planaura_unsupervised_v1"
    assert manifest["classifier_head"] is None
    assert [source["item_id"] for source in manifest["sources"]] == ["s2-a"]
    assert manifest["outputs"][0]["sha256"]
    assert any("unsupervised" in warning for warning in manifest["warnings"])
