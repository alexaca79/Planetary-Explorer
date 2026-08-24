"""Pinned, fail-closed model policy for Planetary Explorer GeoFMs."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class GeoFmProfile(StrEnum):
    """User-facing GeoFM profiles."""

    PLANAURA_HLS = "planaura_hls"


class ApprovalState(StrEnum):
    """Deployment validation state for an exact model revision."""

    APPROVED = "approved"
    CONDITIONAL = "conditional"
    BLOCKED = "blocked"


class ModelDescriptor(BaseModel):
    """Pinned model and preprocessing metadata enforced by the service."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: GeoFmProfile
    model_id: str
    model_revision: str
    checkpoint_filename: str
    checkpoint_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    checkpoint_size_bytes: int = Field(gt=0)
    runtime_repository: str
    runtime_revision: str
    license: str
    required_attribution: str
    approval_state: ApprovalState
    supported_collections: tuple[str, ...]
    band_mapping_by_collection: dict[str, tuple[str, ...]]
    required_quality_asset: str
    native_resolution_m: float = Field(gt=0)
    tile_size_pixels: int = Field(ge=32)
    patch_stride_pixels: int = Field(ge=1)
    normalization_mean: tuple[float, ...]
    normalization_std: tuple[float, ...]
    source_no_data_value: float
    model_no_data_value: float
    minimum_valid_fraction: float = Field(gt=0, le=1)
    preferred_months: tuple[int, ...]
    geographic_scope: str


PLAN_AURA_HLS = ModelDescriptor(
    profile=GeoFmProfile.PLANAURA_HLS,
    model_id="NRCan/Planaura-1.0",
    model_revision="fbbabfdcc0d5e48f7bd05c79b512563cf337742f",
    checkpoint_filename="Planaura-1.0-HLS.pth",
    checkpoint_sha256="cc3041600ec62bc5452f243304ca446c8793e65baf13440cc21c4cf8ba7199eb",
    checkpoint_size_bytes=1_368_772_198,
    runtime_repository="https://github.com/NRCan/planaura.git",
    runtime_revision="a880b26ce08a545b35d6afa431bace39842dd19d",
    license="Open Government Licence - Canada 2.0",
    required_attribution=(
        "Contains information licensed under the Open Government Licence - Canada."
    ),
    approval_state=ApprovalState.CONDITIONAL,
    supported_collections=("hls2-s30", "hls2-l30"),
    band_mapping_by_collection={
        "hls2-s30": ("B02", "B03", "B04", "B8A", "B11", "B12"),
        "hls2-l30": ("B02", "B03", "B04", "B05", "B06", "B07"),
    },
    required_quality_asset="Fmask",
    native_resolution_m=30.0,
    tile_size_pixels=512,
    patch_stride_pixels=16,
    normalization_mean=(643.9851, 845.6229, 788.6456, 2172.8008, 1489.5220, 883.1777),
    normalization_std=(1560.9802, 1540.3963, 1490.3253, 1327.4828, 906.7046, 672.1715),
    source_no_data_value=-9999,
    model_no_data_value=0.0001,
    minimum_valid_fraction=0.7,
    preferred_months=(6, 7, 8, 9),
    geographic_scope="Canada",
)


def get_model(profile: GeoFmProfile | str) -> ModelDescriptor:
    """Resolve an exact profile or fail closed."""
    try:
        parsed = GeoFmProfile(profile)
    except ValueError as exc:
        raise ValueError(f"Unsupported GeoFM profile '{profile}'.") from exc
    if parsed is GeoFmProfile.PLANAURA_HLS:
        return PLAN_AURA_HLS
    raise ValueError(f"Unsupported GeoFM profile '{profile}'.")