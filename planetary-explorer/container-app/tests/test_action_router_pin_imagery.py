"""Point imagery requests must not become temporal raster analyses."""

from __future__ import annotations

import pytest

import pipeline.action_router as action_router_module
from pipeline.action_router import ActionRouter, is_pin_imagery_load, resolve_pin_imagery_followup


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "Show collection sentinel-2-l2a fire false-colour imagery at point on 2026-08-28.",
        "Show Sentinel-2 imagery at the dropped pin on 2026-08-28.",
        "Load the nearest satellite image to August 28, 2026 at this point.",
        "Display false colour imagery here for August 2026.",
    ],
)
async def test_given_pin_display_request_when_routed_then_loads_without_analysis(
    query: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    def unexpected_classifier() -> None:
        raise AssertionError("Explicit pinned imagery must not depend on the classifier")

    monkeypatch.setattr(action_router_module, "get_aoai_client", unexpected_classifier)

    # Act
    decision = await ActionRouter().route(
        query, loaded_collections=["sentinel-2-l2a"], has_pin=True
    )

    # Assert
    assert decision.action == "LOAD"
    assert decision.stac_query == query
    assert decision.use_current_location is True
    assert decision.analysis_question is None


@pytest.mark.parametrize(
    "query",
    [
        "Show imagery here and compare NBR with June.",
        "Show imagery at the pin and assess the damage.",
        "What is the NDVI value at this point?",
        "Show imagery of Toronto on 2026-08-28.",
        "Show me a chart of the NBR comparison at this point.",
    ],
)
def test_given_analysis_or_other_location_when_detecting_pin_load_then_does_not_override(
    query: str,
) -> None:
    # Assert
    assert is_pin_imagery_load(query) is False


@pytest.mark.parametrize(
    "latest_user,followup",
    [
        ("What is the temperature here?", "Find the closest date."),
        ("Show imagery over Toronto on 2026-08-28.", "Find the closest date."),
        ("Show imagery at this pin on 2026-08-28.", "Compare NBR for the nearest date."),
        ("Show imagery at this pin on 2026-08-28.", "Search the web for the closest incident date."),
    ],
)
def test_given_changed_topic_or_analysis_when_resolving_dates_then_does_not_replay_old_imagery(
    latest_user: str, followup: str
) -> None:
    # Arrange
    history = [
        {"role": "user", "content": "Show imagery at this point on 2026-08-28."},
        {"role": "user", "content": latest_user},
        {"role": "assistant", "content": "Show imagery at this point on 2026-08-28."},
    ]

    # Assert
    assert resolve_pin_imagery_followup(followup, history) == followup