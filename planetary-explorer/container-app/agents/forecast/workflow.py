"""Forecast Agent workflow implemented exclusively with Microsoft Agent Framework."""
from __future__ import annotations

import logging
import time
from typing import Any

from connectors.weather.registry import get_registry

from .messages import ForecastAgentQuery

logger = logging.getLogger(__name__)

try:
    from agent_framework import WorkflowBuilder  # type: ignore
    AGENT_FRAMEWORK_AVAILABLE = True
except Exception as exc:  # pragma: no cover
    logger.info("agent_framework not available (%s); forecast MAF workflow disabled", exc)
    AGENT_FRAMEWORK_AVAILABLE = False
    WorkflowBuilder = None  # type: ignore


from .executors import (
    AGENT_FRAMEWORK_AVAILABLE as _EXECUTORS_OK,
    AggregatorExecutor,
    PlannerExecutor,
    ProviderExecutor,
)


def is_available() -> bool:
    return AGENT_FRAMEWORK_AVAILABLE and _EXECUTORS_OK


def _provider_ids_for_build() -> list[str]:
    """All currently-configured provider ids, in registry order."""
    return [p.provider_id for p in get_registry().all]


def _build_workflow(query: ForecastAgentQuery, started_at: float):
    if not is_available():
        raise RuntimeError("Microsoft Agent Framework is required for the Forecast Agent.")
    pids = _provider_ids_for_build()
    if not pids:
        raise RuntimeError(
            "No weather providers configured. Set one or more of "
            "AURORA_ENDPOINT_URL, EARTH2_FCN_ENDPOINT_URL, "
            "MAI_WEATHER_ENDPOINT_URL before running the forecast workflow."
        )

    planner = PlannerExecutor()
    provider_executors = [ProviderExecutor(pid) for pid in pids]
    aggregator = AggregatorExecutor(query=query, started_at=started_at)

    builder = WorkflowBuilder(  # type: ignore[call-arg]
        start_executor=planner,
        output_from=[aggregator],
    )
    builder = builder.add_fan_out_edges(planner, provider_executors)
    builder = builder.add_fan_in_edges(provider_executors, aggregator)
    return builder.build()


# ── Public entry points ──────────────────────────────────────────────────
async def forecast(query: ForecastAgentQuery) -> dict[str, Any]:
    """Run the MAF forecast workflow."""
    if not is_available():
        raise RuntimeError("Microsoft Agent Framework is required for the Forecast Agent.")
    started = time.perf_counter()
    workflow = _build_workflow(query, started_at=started)
    result = await workflow.run(query)
    outputs = result.get_outputs()
    if not outputs:
        raise RuntimeError(
            "Forecast workflow completed with no outputs — aggregator did not "
            "yield_output. Check executor logs."
        )
    return outputs[-1]
