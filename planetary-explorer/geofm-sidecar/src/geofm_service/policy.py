"""Pinned, fail-closed model policy for Planetary Explorer GeoFMs."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GeoFmProfile(str, Enum):
    """User-facing GeoFM profiles."""

    PLANAURA_HLS = "planaura_hls"
    PLANAURA_CLASSIFY_S2 = "planaura_classify_s2"
    PLANAURA_CLASSIFY_S1 = "planaura_classify_s1"
    PLANAURA_CLASSIFY_S3 = "planaura_classify_s3"


class Capability(str, Enum):
    """Work a profile is allowed to perform."""

    CHANGE = "change"
    CLASSIFY = "classify"


class SensorFamily(str, Enum):
    """Physical measurement family a profile ingests."""

    OPTICAL = "optical"
    SAR = "sar"
    COARSE_OPTICAL = "coarse_optical"


class ClassificationMode(str, Enum):
    """How class labels are produced from PlanAura embeddings."""

    UNSUPERVISED = "unsupervised"
    SUPERVISED_LINEAR_PROBE = "supervised_linear_probe"


class ApprovalState(str, Enum):
    """Deployment validation state for an exact model revision."""

    APPROVED = "approved"
    CONDITIONAL = "conditional"
    BLOCKED = "blocked"


class ClassLabel(BaseModel):
    """One label a class scheme can emit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: int = Field(ge=0, le=254)
    name: str = Field(min_length=1, max_length=64)
    colour: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class ClassScheme(BaseModel):
    """Pinned, published label vocabulary with its provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scheme_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    source: str = Field(min_length=1, max_length=300)
    license: str = Field(min_length=1, max_length=200)
    labels: tuple[ClassLabel, ...] = Field(min_length=2, max_length=64)
    no_data_value: int = Field(default=255, ge=0, le=255)


class ClassifierHead(BaseModel):
    """Pinned classifier artefact applied to PlanAura embeddings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    head_id: str = Field(min_length=1, max_length=200)
    head_revision: str = Field(min_length=1, max_length=128)
    filename: str = Field(min_length=1, max_length=200)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    size_bytes: int = Field(gt=0)
    license: str = Field(min_length=1, max_length=200)
    validation_report_uri: str = Field(min_length=1, max_length=2048)


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
    source_resolution_m: tuple[float, ...] = ()
    tile_size_pixels: int = Field(ge=32)
    patch_stride_pixels: int = Field(ge=1)
    normalization_mean: tuple[float, ...]
    normalization_std: tuple[float, ...]
    source_no_data_value: float
    model_no_data_value: float
    minimum_valid_fraction: float = Field(gt=0, le=1)
    preferred_months: tuple[int, ...]
    geographic_scope: str
    capability: Capability = Capability.CHANGE
    sensor_family: SensorFamily = SensorFamily.OPTICAL
    quality_mask_strategy: str = "hls_fmask"
    classification_mode: ClassificationMode | None = None
    class_scheme_id: str | None = None
    classifier_head: ClassifierHead | None = None
    fusion_profile: GeoFmProfile | None = None
    mandatory_warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_capability_invariants(self) -> ModelDescriptor:
        """Reject descriptors whose capability and classification wiring disagree."""
        if self.capability is Capability.CLASSIFY:
            if self.classification_mode is None or not self.class_scheme_id:
                raise ValueError(
                    f"Profile '{self.profile.value}' classifies but has no "
                    "classification mode or class scheme."
                )
            if (
                self.classification_mode is ClassificationMode.SUPERVISED_LINEAR_PROBE
                and self.classifier_head is None
            ):
                raise ValueError(
                    f"Profile '{self.profile.value}' claims a supervised probe "
                    "without a pinned classifier head."
                )
        elif self.classification_mode is not None or self.class_scheme_id:
            raise ValueError(
                f"Profile '{self.profile.value}' does not classify but declares "
                "classification metadata."
            )
        if self.fusion_profile is self.profile:
            raise ValueError(f"Profile '{self.profile.value}' cannot fuse with itself.")
        if self.sensor_family is not SensorFamily.SAR and self.fusion_profile is not None:
            raise ValueError(
                f"Profile '{self.profile.value}' declares a fusion profile but is "
                "not a SAR profile."
            )
        for collection in self.supported_collections:
            if collection not in self.band_mapping_by_collection:
                raise ValueError(
                    f"Profile '{self.profile.value}' supports '{collection}' "
                    "without a band mapping."
                )
        return self

    @property
    def accepted_source_resolutions_m(self) -> tuple[float, ...]:
        """Return the native source grids this profile may resample from."""
        return self.source_resolution_m or (self.native_resolution_m,)


UNSUPERVISED_CLUSTER_SCHEME = ClassScheme(
    scheme_id="planaura_unsupervised_v1",
    title="PlanAura unsupervised cover clusters",
    description=(
        "Clusters of PlanAura patch embeddings named from co-computed spectral "
        "signatures. Cluster names are indicative descriptions, not a validated "
        "semantic land-cover product."
    ),
    source="Derived at run time from PlanAura embeddings and spectral indices.",
    license="Open Government Licence - Canada 2.0",
    labels=(
        ClassLabel(value=0, name="water", colour="#1f78b4"),
        ClassLabel(value=1, name="dense_vegetation", colour="#33a02c"),
        ClassLabel(value=2, name="sparse_vegetation", colour="#b2df8a"),
        ClassLabel(value=3, name="bare_or_built", colour="#bf5b17"),
        ClassLabel(value=4, name="snow_or_ice", colour="#e0e0e0"),
        ClassLabel(value=5, name="burned_or_disturbed", colour="#6a3d9a"),
    ),
)

SAR_SURFACE_SCHEME = ClassScheme(
    scheme_id="planaura_sar_surface_v1",
    title="PlanAura SAR-fused surface clusters",
    description=(
        "Clusters of fused PlanAura optical embeddings and Sentinel-1 RTC "
        "backscatter features. Requires a co-located optical scene."
    ),
    source=(
        "Derived at run time from PlanAura embeddings and Sentinel-1 RTC backscatter."
    ),
    license="Open Government Licence - Canada 2.0",
    labels=(
        ClassLabel(value=0, name="open_water", colour="#1f78b4"),
        ClassLabel(value=1, name="smooth_bare", colour="#d9d9d9"),
        ClassLabel(value=2, name="rough_vegetated", colour="#33a02c"),
        ClassLabel(value=3, name="volume_scattering_forest", colour="#005a32"),
        ClassLabel(value=4, name="double_bounce_built", colour="#e31a1c"),
    ),
)

COARSE_REGIME_SCHEME = ClassScheme(
    scheme_id="planaura_coarse_regime_v1",
    title="PlanAura coarse regional regimes",
    description=(
        "Regional aggregate regimes at Sentinel-3 resolution. Valid only for "
        "regional summaries, never for per-parcel or per-field statements."
    ),
    source="Derived at run time from Sentinel-3 OLCI and SLSTR Level-2 products.",
    license="Open Government Licence - Canada 2.0",
    labels=(
        ClassLabel(value=0, name="water_regime", colour="#1f78b4"),
        ClassLabel(value=1, name="vegetated_land_regime", colour="#33a02c"),
        ClassLabel(value=2, name="bare_land_regime", colour="#bf5b17"),
        ClassLabel(value=3, name="warm_thermal_regime", colour="#e31a1c"),
        ClassLabel(value=4, name="cool_thermal_regime", colour="#a6cee3"),
    ),
)

CLASS_SCHEMES: dict[str, ClassScheme] = {
    scheme.scheme_id: scheme
    for scheme in (
        UNSUPERVISED_CLUSTER_SCHEME,
        SAR_SURFACE_SCHEME,
        COARSE_REGIME_SCHEME,
    )
}

UNSUPERVISED_WARNING = (
    "Labels are unsupervised, cluster-derived descriptions, not a validated "
    "semantic land-cover product."
)

_PLANAURA_CHECKPOINT: dict[str, object] = {
    "model_id": "NRCan/Planaura-1.0",
    "model_revision": "fbbabfdcc0d5e48f7bd05c79b512563cf337742f",
    "checkpoint_filename": "Planaura-1.0-HLS.pth",
    "checkpoint_sha256": (
        "cc3041600ec62bc5452f243304ca446c8793e65baf13440cc21c4cf8ba7199eb"
    ),
    "checkpoint_size_bytes": 1_368_772_198,
    "runtime_repository": "https://github.com/NRCan/planaura.git",
    "runtime_revision": "a880b26ce08a545b35d6afa431bace39842dd19d",
    "license": "Open Government Licence - Canada 2.0",
    "required_attribution": (
        "Contains information licensed under the Open Government Licence - Canada."
    ),
    "normalization_mean": (
        643.9851,
        845.6229,
        788.6456,
        2172.8008,
        1489.5220,
        883.1777,
    ),
    "normalization_std": (
        1560.9802,
        1540.3963,
        1490.3253,
        1327.4828,
        906.7046,
        672.1715,
    ),
    "source_no_data_value": -9999,
    "model_no_data_value": 0.0001,
    "patch_stride_pixels": 16,
    "tile_size_pixels": 512,
    "preferred_months": (6, 7, 8, 9),
    "geographic_scope": "Canada",
}


PLAN_AURA_HLS = ModelDescriptor(
    profile=GeoFmProfile.PLANAURA_HLS,
    **_PLANAURA_CHECKPOINT,
    approval_state=ApprovalState.CONDITIONAL,
    supported_collections=("hls2-s30", "hls2-l30"),
    band_mapping_by_collection={
        "hls2-s30": ("B02", "B03", "B04", "B8A", "B11", "B12"),
        "hls2-l30": ("B02", "B03", "B04", "B05", "B06", "B07"),
    },
    required_quality_asset="Fmask",
    native_resolution_m=30.0,
    minimum_valid_fraction=0.7,
    capability=Capability.CHANGE,
    sensor_family=SensorFamily.OPTICAL,
    quality_mask_strategy="hls_fmask",
)

PLAN_AURA_CLASSIFY_S2 = ModelDescriptor(
    profile=GeoFmProfile.PLANAURA_CLASSIFY_S2,
    **_PLANAURA_CHECKPOINT,
    approval_state=ApprovalState.CONDITIONAL,
    supported_collections=("sentinel-2-l2a",),
    band_mapping_by_collection={
        "sentinel-2-l2a": ("B02", "B03", "B04", "B8A", "B11", "B12"),
    },
    required_quality_asset="SCL",
    native_resolution_m=30.0,
    source_resolution_m=(10.0, 20.0, 60.0),
    minimum_valid_fraction=0.7,
    capability=Capability.CLASSIFY,
    sensor_family=SensorFamily.OPTICAL,
    quality_mask_strategy="sentinel2_scl",
    classification_mode=ClassificationMode.UNSUPERVISED,
    class_scheme_id=UNSUPERVISED_CLUSTER_SCHEME.scheme_id,
    mandatory_warnings=(UNSUPERVISED_WARNING,),
)

PLAN_AURA_CLASSIFY_S1 = ModelDescriptor(
    profile=GeoFmProfile.PLANAURA_CLASSIFY_S1,
    **_PLANAURA_CHECKPOINT,
    approval_state=ApprovalState.BLOCKED,
    supported_collections=("sentinel-1-rtc",),
    band_mapping_by_collection={"sentinel-1-rtc": ("vv", "vh")},
    required_quality_asset="mask",
    native_resolution_m=10.0,
    source_resolution_m=(10.0, 20.0),
    minimum_valid_fraction=0.7,
    capability=Capability.CLASSIFY,
    sensor_family=SensorFamily.SAR,
    quality_mask_strategy="sentinel1_rtc_mask",
    classification_mode=ClassificationMode.UNSUPERVISED,
    class_scheme_id=SAR_SURFACE_SCHEME.scheme_id,
    fusion_profile=GeoFmProfile.PLANAURA_CLASSIFY_S2,
    mandatory_warnings=(
        UNSUPERVISED_WARNING,
        "Sentinel-1 results fuse SAR backscatter with optical embeddings; "
        "backscatter alone does not determine land cover.",
    ),
)

PLAN_AURA_CLASSIFY_S3 = ModelDescriptor(
    profile=GeoFmProfile.PLANAURA_CLASSIFY_S3,
    **_PLANAURA_CHECKPOINT,
    approval_state=ApprovalState.BLOCKED,
    supported_collections=(
        "sentinel-3-olci-wfr-l2-netcdf",
        "sentinel-3-slstr-wst-l2-netcdf",
    ),
    band_mapping_by_collection={
        "sentinel-3-olci-wfr-l2-netcdf": (
            "oa04-reflectance",
            "oa06-reflectance",
            "oa08-reflectance",
            "oa17-reflectance",
        ),
        "sentinel-3-slstr-wst-l2-netcdf": ("sea-surface-temperature",),
    },
    required_quality_asset="wqsf",
    native_resolution_m=300.0,
    source_resolution_m=(300.0, 500.0, 1000.0),
    minimum_valid_fraction=0.5,
    capability=Capability.CLASSIFY,
    sensor_family=SensorFamily.COARSE_OPTICAL,
    quality_mask_strategy="sentinel3_quality_flags",
    classification_mode=ClassificationMode.UNSUPERVISED,
    class_scheme_id=COARSE_REGIME_SCHEME.scheme_id,
    mandatory_warnings=(
        UNSUPERVISED_WARNING,
        "Sentinel-3 pixels are 300 m or coarser; results are regional and "
        "indicative only, never per-parcel.",
    ),
)

_REGISTRY: dict[GeoFmProfile, ModelDescriptor] = {
    descriptor.profile: descriptor
    for descriptor in (
        PLAN_AURA_HLS,
        PLAN_AURA_CLASSIFY_S2,
        PLAN_AURA_CLASSIFY_S1,
        PLAN_AURA_CLASSIFY_S3,
    )
}


def get_model(profile: GeoFmProfile | str) -> ModelDescriptor:
    """Resolve an exact profile or fail closed."""
    try:
        parsed = GeoFmProfile(profile)
    except ValueError as exc:
        raise ValueError(f"Unsupported GeoFM profile '{profile}'.") from exc
    descriptor = _REGISTRY.get(parsed)
    if descriptor is None:
        raise ValueError(f"Unsupported GeoFM profile '{profile}'.")
    return descriptor


def list_models() -> tuple[ModelDescriptor, ...]:
    """Return every registered profile in a stable order."""
    return tuple(_REGISTRY.values())


def get_class_scheme(scheme_id: str) -> ClassScheme:
    """Resolve an exact class scheme or fail closed."""
    scheme = CLASS_SCHEMES.get(scheme_id)
    if scheme is None:
        raise ValueError(f"Unsupported class scheme '{scheme_id}'.")
    return scheme


def list_class_schemes() -> tuple[ClassScheme, ...]:
    """Return every published class scheme in a stable order."""
    return tuple(CLASS_SCHEMES.values())


def get_fusion_model(descriptor: ModelDescriptor) -> ModelDescriptor | None:
    """Resolve the optical descriptor a SAR profile must fuse with."""
    if descriptor.fusion_profile is None:
        return None
    return get_model(descriptor.fusion_profile.value)


def supported_collections() -> tuple[str, ...]:
    """Return every collection any registered profile can ingest."""
    collections: list[str] = []
    for descriptor in _REGISTRY.values():
        for collection in descriptor.supported_collections:
            if collection not in collections:
                collections.append(collection)
    return tuple(collections)