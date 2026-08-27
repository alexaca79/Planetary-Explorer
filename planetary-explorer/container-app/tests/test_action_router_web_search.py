"""Layer-1 routing regressions for explicit public-web intent."""

from __future__ import annotations

import pytest

import pipeline.action_router as action_router_module
from pipeline.action_router import ActionRouter, is_explicit_web_request


@pytest.mark.parametrize(
    "query",
    [
        "Search the web for the latest Microsoft Foundry update.",
        "Browse the public web for current wildfire news.",
        "Look up this announcement on the web.",
        "Run a web search for today's AI news.",
    ],
)
def test_given_explicit_web_language_when_detected_then_returns_true(query: str) -> None:
    # Assert
    assert is_explicit_web_request(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "Search for Paris on the map.",
        "Show me Web Lake, Wisconsin.",
        "Load the latest Sentinel-2 imagery.",
    ],
)
def test_given_map_language_when_detected_then_returns_false(query: str) -> None:
    # Assert
    assert is_explicit_web_request(query) is False


@pytest.mark.asyncio
async def test_given_explicit_web_request_when_routed_then_skips_classifier(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setattr(
        action_router_module,
        "get_aoai_client",
        lambda: (_ for _ in ()).throw(AssertionError("classifier must be skipped")),
    )

    # Act
    decision = await ActionRouter().route(
        "Search the web for the latest Microsoft Foundry update."
    )

    # Assert
    assert decision.action == "ANALYZE"
    assert decision.reasoning == "explicit_web_search"