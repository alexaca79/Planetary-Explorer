"""Tests for the Terrain Agent compatibility contract."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from geoint.terrain_agent import TerrainAgent, TerrainAgentSession


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


@pytest.mark.asyncio
async def test_given_failed_synthesis_when_tool_completed_then_returns_measured_evidence(
    monkeypatch,
) -> None:
    # Arrange
    agent = TerrainAgent()
    agent._initialized = True
    agent._agent_id = "terrain-agent"
    agent.sessions["banff-2026"] = TerrainAgentSession(
        "banff-2026",
        51.0641,
        -114.28542,
        "thread-banff",
    )

    async def create_message(**_kwargs):
        return None

    async def create_run(**_kwargs):
        return SimpleNamespace(
            id="run-rate-limited",
            status="failed",
            last_error={"code": "rate_limit_exceeded"},
        )

    async def run_steps():
        function = SimpleNamespace(
            name="get_elevation_analysis",
            output=(
                '{"elevation_min_meters": 1056.5, '
                '"elevation_max_meters": 1290.8, '
                '"elevation_mean_meters": 1169.3, '
                '"terrain_type": "hilly terrain", '
                '"data_source": "Copernicus DEM GLO-30"}'
            ),
        )
        yield SimpleNamespace(
            step_details=SimpleNamespace(
                tool_calls=[SimpleNamespace(function=function)]
            )
        )

    agent._agents_client = SimpleNamespace(
        messages=SimpleNamespace(create=create_message),
        runs=SimpleNamespace(create_and_process=create_run),
        run_steps=SimpleNamespace(list=lambda **_kwargs: run_steps()),
    )

    async def reverse_geocode(_latitude: float, _longitude: float) -> str:
        return '{"name":"Banff","region":"Alberta","country":"Canada"}'

    monkeypatch.setattr(
        "semantic_translator.geocoding_plugin.azure_maps_reverse_geocode",
        reverse_geocode,
    )

    # Act
    result = await agent.chat(
        session_id="banff-2026",
        user_message="What is the elevation?",
        latitude=51.0641,
        longitude=-114.28542,
        radius_km=8.05,
    )

    # Assert
    assert result["synthesis_degraded"] is True
    assert "Mean: 1169.3 metres" in result["response"]
    assert "1056.5 to 1290.8 metres" in result["response"]
    assert result["tool_calls"] == [
        {
            "tool": "get_elevation_analysis",
            "result": {
                "elevation_min_meters": 1056.5,
                "elevation_max_meters": 1290.8,
                "elevation_mean_meters": 1169.3,
                "terrain_type": "hilly terrain",
                "data_source": "Copernicus DEM GLO-30",
            },
        }
    ]