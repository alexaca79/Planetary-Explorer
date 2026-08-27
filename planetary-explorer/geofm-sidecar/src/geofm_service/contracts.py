"""Typed GeoFM requests, durable run records, and reduced evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum, IntEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

GeoJson = dict[str, JsonValue]
UTC = timezone.utc


class EvidenceRung(IntEnum):
    """Lowest reduced evidence form sufficient for an answer."""

    CATALOGUE = 0
    STATISTIC = 1
    VECTOR = 2
    ARTEFACT = 3


class EvidenceReference(BaseModel):
    """Traceable source or derived artefact supporting a response."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["stac_item", "artefact", "calculation"]
    identifier: str = Field(min_length=1, max_length=512)
    uri: str | None = Field(default=None, max_length=2048)
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")


class EvidenceEnvelope(BaseModel):
    """Bounded evidence safe to expose to the Planetary Explorer agent."""

    model_config = ConfigDict(extra="forbid")

    operation_id: UUID = Field(default_factory=uuid4)
    evidence_rung: EvidenceRung
    summary: str = Field(min_length=1, max_length=4000)
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def reject_unreduced_evidence(self) -> EvidenceEnvelope:
        """Reject raster-like or embedding arrays before agent exposure."""
        forbidden_keys = {
            "band_data",
            "embedding_table",
            "full_embedding",
            "pixel_array",
            "pixels",
            "raster_values",
        }

        def inspect(value: JsonValue, path: str) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized = key.casefold()
                    if normalized in forbidden_keys or normalized.startswith(
                        ("raw_embedding", "raw_pixels", "raw_raster")
                    ):
                        raise ValueError(
                            f"Unreduced evidence is not allowed at '{path}.{key}'. "
                            "Persist it as an artefact and return a reference instead."
                        )
                    inspect(child, f"{path}.{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    inspect(child, f"{path}[{index}]")

        inspect(self.payload, "payload")
        return self


class RunStatus(str, Enum):
    """Persisted lifecycle states for GeoFM work."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CompareEpochsRequest(BaseModel):
    """Fully specified bi-temporal GeoFM request."""

    model_config = ConfigDict(extra="forbid")

    geometry: GeoJson
    item_id_epoch_a: str = Field(min_length=1, max_length=512)
    item_id_epoch_b: str = Field(min_length=1, max_length=512)
    profile: str = "planaura_hls"
    correlation_id: str = Field(min_length=1, max_length=128)
    requested_by: str = Field(min_length=1, max_length=256)
    threshold: float = Field(default=0.35, ge=0, le=2)
    max_features: int = Field(default=10, ge=1, le=100)


class RunArtifact(BaseModel):
    """Durable derived artefact; bytes remain outside model context."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=64)
    uri: str = Field(min_length=1, max_length=2048)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class RunRecord(BaseModel):
    """Persisted GeoFM run and its validated result manifest."""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID = Field(default_factory=uuid4)
    idempotency_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    version: int = Field(default=0, ge=0)
    attempt: int = Field(default=1, ge=1)
    status: RunStatus = RunStatus.QUEUED
    worker_id: str | None = Field(default=None, max_length=128)
    lease_expires_at: datetime | None = None
    request: CompareEpochsRequest
    selected_model: dict[str, JsonValue]
    preprocessing_recipe: dict[str, JsonValue]
    warnings: list[str] = Field(default_factory=list, max_length=20)
    progress_pct: int = Field(default=0, ge=0, le=100)
    artifacts: list[RunArtifact] = Field(default_factory=list, max_length=20)
    statistics: dict[str, JsonValue] = Field(default_factory=dict)
    features: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=100)
    error: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))