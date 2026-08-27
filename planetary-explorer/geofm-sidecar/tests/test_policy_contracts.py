"""Policy and evidence-boundary tests for the GeoFM sidecar."""

import pytest
from pydantic import ValidationError

from geofm_service.contracts import EvidenceEnvelope, EvidenceReference, EvidenceRung
from geofm_service.policy import PLAN_AURA_HLS, ApprovalState, get_model


def test_given_planaura_profile_when_resolved_then_exact_revisions_are_pinned() -> None:
    # Act
    descriptor = get_model("planaura_hls")

    # Assert
    assert descriptor.model_revision == "fbbabfdcc0d5e48f7bd05c79b512563cf337742f"
    assert descriptor.checkpoint_sha256 == (
        "cc3041600ec62bc5452f243304ca446c8793e65baf13440cc21c4cf8ba7199eb"
    )
    assert descriptor.runtime_repository == "https://github.com/NRCan/planaura.git"
    assert descriptor.runtime_revision == "a880b26ce08a545b35d6afa431bace39842dd19d"


def test_given_planaura_profile_when_listed_then_gpu_gate_remains_conditional() -> None:
    # Assert
    assert PLAN_AURA_HLS.approval_state is ApprovalState.CONDITIONAL


def test_given_hls_collections_when_reading_policy_then_sensor_bands_are_mapped() -> None:
    # Act
    sentinel_bands = PLAN_AURA_HLS.band_mapping_by_collection["hls2-s30"]
    landsat_bands = PLAN_AURA_HLS.band_mapping_by_collection["hls2-l30"]

    # Assert
    assert sentinel_bands == ("B02", "B03", "B04", "B8A", "B11", "B12")
    assert landsat_bands == ("B02", "B03", "B04", "B05", "B06", "B07")


def test_given_pixel_array_when_building_evidence_then_validation_rejects_it() -> None:
    # Act & Assert
    with pytest.raises(ValidationError, match="Unreduced evidence"):
        EvidenceEnvelope(
            evidence_rung=EvidenceRung.STATISTIC,
            summary="Invalid evidence",
            payload={"pixel_array": [[1, 2], [3, 4]]},
            evidence=[EvidenceReference(kind="calculation", identifier="test")],
        )


def test_given_statistics_and_features_when_building_evidence_then_it_is_allowed() -> None:
    # Act
    envelope = EvidenceEnvelope(
        evidence_rung=EvidenceRung.VECTOR,
        summary="Validated change evidence",
        payload={
            "statistics": {"changed_area_km2": 1.2},
            "features": [{"geometry": {"type": "Polygon", "coordinates": []}}],
        },
        evidence=[EvidenceReference(kind="calculation", identifier="run-1")],
    )

    # Assert
    assert envelope.payload["statistics"] == {"changed_area_km2": 1.2}