"""Tests for Agent Service tool execution helpers."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from azure.ai.agents.models import AsyncFunctionTool

from geoint.tool_runtime import (
    merge_recorded_tool_results,
    offload_blocking_tools,
    record_tool_results,
)


def measure_slope(latitude: float, longitude: float, radius_km: float = 5.0) -> str:
    """Measure terrain slope around a point.

    :param latitude: Centre latitude in decimal degrees.
    :param longitude: Centre longitude in decimal degrees.
    :param radius_km: Analysis radius in kilometres.
    :return: JSON slope summary.
    """
    time.sleep(0.2)
    return f'{{"thread": {threading.get_ident()}, "latitude": {latitude}}}'


def test_given_sync_tools_when_offloaded_then_published_definitions_are_unchanged() -> None:
    # Arrange
    original = AsyncFunctionTool({measure_slope})

    # Act
    offloaded = AsyncFunctionTool(offload_blocking_tools({measure_slope}))

    # Assert
    assert [item.as_dict() for item in offloaded.definitions] == [
        item.as_dict() for item in original.definitions
    ]


@pytest.mark.asyncio
async def test_given_blocking_tool_when_awaited_then_event_loop_keeps_running() -> None:
    # Arrange
    (tool,) = offload_blocking_tools({measure_slope})
    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    # Act
    beat = asyncio.create_task(heartbeat())
    with record_tool_results() as recorded:
        output = await tool(latitude=62.454, longitude=-114.372)
    beat.cancel()

    # Assert
    assert ticks >= 5
    assert recorded[0]["tool"] == "measure_slope"
    assert recorded[0]["result"]["latitude"] == 62.454
    assert recorded[0]["result"]["thread"] != threading.get_ident()
    assert output.startswith('{"thread"')


@pytest.mark.asyncio
async def test_given_no_recorder_when_tool_runs_then_nothing_is_retained() -> None:
    # Arrange
    (tool,) = offload_blocking_tools({measure_slope})

    # Act
    with record_tool_results() as outer:
        pass
    await tool(latitude=45.4215, longitude=-75.6972)

    # Assert
    assert outer == []


def test_given_missing_run_step_output_when_merged_then_recorded_result_is_used() -> None:
    # Arrange
    run_steps = [
        {"tool": "get_slope_analysis", "result": None},
        {"tool": "analyze_flood_risk", "result": {"flood_risk_level": "LOW"}},
    ]
    recorded = [
        {"tool": "analyze_flood_risk", "result": {"flood_risk_level": "HIGH"}},
        {"tool": "get_slope_analysis", "result": {"slope_mean_degrees": 3.1}},
        {"tool": "find_flat_areas", "result": {"flat_area_percent": 70.0}},
    ]

    # Act
    merged = merge_recorded_tool_results(run_steps, recorded)

    # Assert
    assert merged == [
        {"tool": "get_slope_analysis", "result": {"slope_mean_degrees": 3.1}},
        {"tool": "analyze_flood_risk", "result": {"flood_risk_level": "LOW"}},
        {"tool": "find_flat_areas", "result": {"flat_area_percent": 70.0}},
    ]
