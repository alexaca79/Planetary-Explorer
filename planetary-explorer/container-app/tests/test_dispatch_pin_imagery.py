"""Pinned imagery intent survives clarifier hints and nearest-date follow-ups."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import pipeline.dispatch as dispatch_module
import pipeline.layer1_agents as layer1_module
from pipeline.contracts import ActionDecision, AnalysisRequest
from pipeline.dispatch import run_pipeline_v2


@pytest.fixture
def capture_dispatch(monkeypatch: pytest.MonkeyPatch) -> list[tuple[ActionDecision, AnalysisRequest]]:
    captured: list[tuple[ActionDecision, AnalysisRequest]] = []

    async def capture(decision: ActionDecision, request: AnalysisRequest, body: dict) -> dict:
        captured.append((decision, request))
        return {"action": decision.action}

    async def classify(**kwargs: object) -> ActionDecision:
        return ActionDecision(action="ANALYZE", analysis_question=str(kwargs.get("query")))

    monkeypatch.setattr(
        dispatch_module,
        "build_default_pipeline",
        lambda: (SimpleNamespace(route=classify), None, None, None),
    )
    monkeypatch.setattr(
        layer1_module,
        "build_layer1_agents",
        lambda **kwargs: SimpleNamespace(for_action=lambda action: SimpleNamespace(run=capture)),
    )
    return captured


@pytest.mark.asyncio
@pytest.mark.parametrize("clarifier_route", [None, "contextual", "vision_analysis", "hybrid"])
async def test_given_explicit_pin_load_when_clarifier_suggests_analysis_then_load_wins(
    clarifier_route: str | None, capture_dispatch: list
) -> None:
    # Arrange
    query = "Show collection sentinel-2-l2a fire false-colour imagery at point on 2026-08-28."

    # Act
    await run_pipeline_v2({
        "query": query,
        "pin": {"lat": 49.5508, "lng": -122.9015},
        "map_bounds": [-124, 48, -120, 51],
        "clarifier_route": clarifier_route,
    })

    # Assert
    decision, request = capture_dispatch[0]
    assert decision.action == "LOAD"
    assert decision.stac_query == query
    assert decision.analysis_question is None
    assert request.bbox is None


@pytest.mark.asyncio
async def test_given_nearest_date_followup_and_moved_pin_then_loads_prior_imagery_at_new_pin(
    capture_dispatch: list,
) -> None:
    # Arrange
    prior = "Show collection sentinel-2-l2a fire false-colour imagery at point on 2026-08-28."

    # Act
    await run_pipeline_v2({
        "query": "find the date that has it please closes to that date",
        "pin": {"lat": 49.432296, "lng": -122.482823},
        "map_bounds": [-124, 48, -120, 51],
        "clarifier_route": "contextual",
        "conversation_history": [
            {"role": "user", "content": prior},
            {"role": "assistant", "content": "No single scene fully covers the requested extent."},
        ],
    })

    # Assert
    decision, request = capture_dispatch[0]
    assert decision.action == "LOAD"
    assert "sentinel-2-l2a" in decision.stac_query
    assert "2026-08-28" in decision.stac_query
    assert "nearest" in decision.stac_query
    assert "fire false-colour" in request.question
    assert request.pin == (49.432296, -122.482823)
    assert request.bbox is None