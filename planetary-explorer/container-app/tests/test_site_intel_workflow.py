"""End-to-end test for the Site Intel Microsoft Agent Framework graph."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from agents import site_audit
from agents.site_intel import executors, workflow


LAKEHOUSE_SEED = Path(__file__).resolve().parents[3] / "data" / "lakehouse_seed"


@pytest.mark.asyncio
async def test_given_missing_fabric_ids_when_table_loads_then_uses_bundled_seed() -> None:
    # Arrange
    site_audit._TABLE_CACHE.clear()
    site_audit._TABLE_VERSIONS.clear()
    site_audit._load_seed_tables.cache_clear()

    try:
        # Act
        frame = await site_audit._load_table("candidate_sites", "assertion", "", "")

        # Assert
        assert frame.attrs["source"] == "bundled_seed"
        assert frame["site_id"].str.startswith("ca-").all()
    finally:
        site_audit._TABLE_CACHE.clear()
        site_audit._TABLE_VERSIONS.clear()


@pytest.mark.asyncio
@pytest.mark.skipif(not workflow.is_available(), reason="agent_framework not installed")
async def test_given_canadian_seed_when_site_workflow_runs_then_maf_yields_dossier(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setenv("SITE_PLANNER", "0")
    monkeypatch.setenv("SITE_EVIDENCE", "0")
    monkeypatch.setenv("SITE_REVIEW", "0")
    executors._RETRIEVAL_CACHE.clear()

    async def load_table(
        table: str,
        _user_assertion: str,
        _workspace_id: str,
        _lakehouse_id: str,
    ) -> pd.DataFrame:
        frame = pd.read_parquet(LAKEHOUSE_SEED / f"{table}.parquet")
        frame.attrs["source"] = "bundled_seed"
        return frame

    async def score_hazards(
        _lat: float,
        _lng: float,
        _user_query: str | None,
    ) -> site_audit.DimensionResult:
        return site_audit.DimensionResult(
            score=82.0,
            summary="Canadian 2026 hazard evidence available.",
            evidence=[{"kind": "mpc_dynamic_match", "collection": "sentinel-2-l2a"}],
        )

    async def score_precedent(
        _assertion: str,
        _workspace_id: str,
        _lat: float,
        _lng: float,
        _claimed_mw: float,
    ) -> site_audit.DimensionResult:
        return site_audit.DimensionResult(
            score=74.0,
            summary="Canadian permitting demo evidence available.",
            evidence=[{"kind": "precedent", "doc_id": "ca-demo-2026"}],
        )

    monkeypatch.setattr(executors, "_load_table", load_table)
    monkeypatch.setattr(executors, "_score_hazards_with_mpc", score_hazards)
    monkeypatch.setattr(executors, "_score_precedent_with_search", score_precedent)

    # Act
    dossier = await workflow.audit_site_v2(
        user_assertion="test-assertion",
        lat=51.18,
        lng=-114.05,
        claimed_mw=200,
        user_query="Score this 2026 Calgary site.",
        workspace_id="test-workspace",
        lakehouse_id="test-lakehouse",
    )

    # Assert
    assert dossier["engine"] == "maf_workflow_v2"
    assert dossier["input"]["lat"] == 51.18
    assert dossier["scores"]["overall"] >= 0
    assert set(dossier["scores"]) >= {
        "power",
        "water",
        "hazards",
        "competition",
        "parcel_match",
        "precedent",
        "overall",
    }
    assert any(
        row.get("table") == "candidate_sites"
        and row.get("source") == "bundled_seed"
        and row.get("authoritative") is False
        for row in dossier["data_provenance"]
    )