"""Tests for the Terrain Agent compatibility contract."""

from __future__ import annotations

import pytest

from geoint.terrain_agent import TerrainAgent


@pytest.mark.asyncio
async def test_given_analyze_caller_when_invoked_then_delegates_to_chat(
    monkeypatch,
) -> None:
    # Arrange
    agent = TerrainAgent()
    calls: list[dict[str, object]] = []
    expected = {
        "response": "Elevation is 1,383 metres.",
        "tool_calls": [{"tool": "get_elevation_analysis"}],
    }

    async def fake_chat(**kwargs):
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(agent, "chat", fake_chat)

    # Act
    result = await agent.analyze(
        session_id="banff-2026",
        user_message="What is the elevation?",
        latitude=51.0641,
        longitude=-114.28542,
        screenshot_base64="image-data",
        radius_km=8.05,
    )

    # Assert
    assert result == expected
    assert calls == [
        {
            "session_id": "banff-2026",
            "user_message": "What is the elevation?",
            "latitude": 51.0641,
            "longitude": -114.28542,
            "screenshot_base64": "image-data",
            "radius_km": 8.05,
        }
    ]