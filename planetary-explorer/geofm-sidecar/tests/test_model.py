"""Lightweight PlanAura adapter tests that do not load model weights."""

import hashlib
from pathlib import Path

import numpy as np
import pytest

from geofm_service.model import (
    ModelRuntimeError,
    build_planaura_config,
    normalize_epochs,
    similarity_to_distance,
    verify_checkpoint,
)
from geofm_service.policy import PLAN_AURA_HLS


def test_given_matching_checkpoint_when_verifying_then_it_succeeds(tmp_path: Path) -> None:
    # Arrange
    checkpoint = tmp_path / "checkpoint.pth"
    checkpoint.write_bytes(b"known checkpoint")
    digest = hashlib.sha256(b"known checkpoint").hexdigest()

    # Act
    verify_checkpoint(checkpoint, digest, len(b"known checkpoint"))

    # Assert
    assert checkpoint.is_file()


def test_given_wrong_checkpoint_when_verifying_then_it_fails_before_inference(
    tmp_path: Path,
) -> None:
    # Arrange
    checkpoint = tmp_path / "checkpoint.pth"
    checkpoint.write_bytes(b"unexpected")

    # Act & Assert
    with pytest.raises(ModelRuntimeError, match="Checkpoint hash mismatch"):
        verify_checkpoint(checkpoint, "0" * 64)


def test_given_policy_when_building_config_then_real_upstream_contract_is_used(
    tmp_path: Path,
) -> None:
    # Act
    config = build_planaura_config(PLAN_AURA_HLS, tmp_path / "model.pth")

    # Assert
    assert config["num_frames"] == 2
    assert config["change_map"] == {"return": True}
    assert config["feature_maps"] == {"return": False}
    assert config["model_params"]["backbone"] == "planaura_reconstruction"
    assert config["model_params"]["img_size"] == 512


def test_given_nodata_when_normalizing_then_model_sentinel_is_preserved() -> None:
    # Arrange
    shape = (1, 6, 2, 512, 512)
    values = np.zeros(shape, dtype=np.float32)
    values[0, 0, 0, 0, 0] = -9999

    # Act
    normalized = normalize_epochs(values, PLAN_AURA_HLS)

    # Assert
    assert normalized[0, 0, 0, 0, 0] == pytest.approx(0.0001)
    assert normalized[0, 0, 0, 0, 1] == pytest.approx(
        -PLAN_AURA_HLS.normalization_mean[0] / PLAN_AURA_HLS.normalization_std[0]
    )


def test_given_cosine_similarity_when_converting_then_distance_is_bounded() -> None:
    # Arrange
    similarity = np.array([[1.0, 0.25, -1.0, -100.0]], dtype=np.float32)

    # Act
    distance = similarity_to_distance(similarity)

    # Assert
    assert distance[0, :3].tolist() == pytest.approx([0.0, 0.75, 2.0])
    assert np.isnan(distance[0, 3])