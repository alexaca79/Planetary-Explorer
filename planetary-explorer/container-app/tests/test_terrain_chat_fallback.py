"""Terrain chat fallback contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


class _JsonRequest:
    async def json(self) -> dict:
        return {
            "session_id": "terrain-fallback",
            "message": "Summarize the terrain.",
            "latitude": 51.0447,
            "longitude": -114.0719,
            "radius_km": 5.0,
        }


@pytest.mark.asyncio
async def test_given_agent_failure_when_chatting_then_shared_client_synthesizes_tools(
    monkeypatch,
) -> None:
    # Arrange
    import fastapi_app
    import geoint.terrain_agent as agent_module
    import geoint.terrain_tools as tools_module
    import pipeline._aoai as aoai_module

    class FailingAgent:
        async def chat(self, **_kwargs):
            raise RuntimeError("agent unavailable")

    class FakeCompletions:
        async def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content="synthesized"))
                ]
            )

    factory_calls = []
    monkeypatch.setattr(agent_module, "get_terrain_agent", lambda: FailingAgent())
    monkeypatch.setattr(tools_module, "get_elevation_analysis", lambda *_args: "100 m")
    monkeypatch.setattr(tools_module, "get_slope_analysis", lambda *_args: "5 degrees")
    monkeypatch.setattr(tools_module, "find_flat_areas", lambda *_args: "flat")
    monkeypatch.setattr(tools_module, "analyze_flood_risk", lambda *_args: "low")
    monkeypatch.setattr(
        aoai_module,
        "get_aoai_client",
        lambda: (
            factory_calls.append(True)
            or SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        ),
    )

    # Act
    result = await fastapi_app.geoint_terrain_chat(_JsonRequest())

    # Assert
    assert factory_calls == [True]
    assert result["status"] == "success"
    assert result["response"] == "synthesized"
    assert result["tool_calls"] == [
        {"tool": "get_elevation_analysis", "result": "100 m"},
        {"tool": "get_slope_analysis", "result": "5 degrees"},
        {"tool": "find_flat_areas", "result": "flat"},
        {"tool": "analyze_flood_risk", "result": "low"},
    ]


@pytest.mark.asyncio
async def test_given_blocking_fallback_tools_when_chatting_then_event_loop_stays_responsive(
    monkeypatch,
) -> None:
    # Arrange
    import asyncio
    import threading
    import time

    import fastapi_app
    import geoint.terrain_agent as agent_module
    import geoint.terrain_tools as tools_module
    import pipeline._aoai as aoai_module

    class FailingAgent:
        async def chat(self, **_kwargs):
            raise RuntimeError("agent unavailable")

    class FakeCompletions:
        async def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )

    loop_thread = threading.get_ident()
    tool_threads: list[int] = []

    def blocking_tool(*_args):
        tool_threads.append(threading.get_ident())
        time.sleep(0.2)
        return '{"value": 1}'

    monkeypatch.setattr(agent_module, "get_terrain_agent", lambda: FailingAgent())
    for name in (
        "get_elevation_analysis",
        "get_slope_analysis",
        "find_flat_areas",
        "analyze_flood_risk",
    ):
        monkeypatch.setattr(tools_module, name, blocking_tool)
    monkeypatch.setattr(
        aoai_module,
        "get_aoai_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )
    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    # Act
    beat = asyncio.create_task(heartbeat())
    started = time.perf_counter()
    result = await fastapi_app.geoint_terrain_chat(_JsonRequest())
    elapsed = time.perf_counter() - started
    beat.cancel()

    # Assert
    assert loop_thread not in tool_threads
    assert elapsed < 0.6
    assert ticks >= 5
    assert [call["result"] for call in result["tool_calls"]] == [{"value": 1}] * 4
