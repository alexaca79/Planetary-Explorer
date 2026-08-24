"""Bounded Analyst Agent behavior tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agents.analyst_agent.analyst_agent import AnalystAgent, AnalystThread
from agents.analyst_agent.session_context import get_session
from pipeline.contracts import ActionDecision, AnalysisRequest
from pipeline.layer1_agents import LoadAndAnalyzeAgent


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        question="How severe were Ontario fires?",
        session_id="session-1",
        location_name="Ontario, Canada",
        stac_mode="public",
    )


class _FakeRuns:
    def __init__(self) -> None:
        self.cancelled: list[tuple[str, str]] = []

    def list(self, *, thread_id, limit, order):
        async def items():
            yield SimpleNamespace(id="run-active", status="in_progress")
            yield SimpleNamespace(id="run-complete", status="completed")

        return items()

    async def cancel(self, *, thread_id, run_id):
        self.cancelled.append((thread_id, run_id))


def _attach_active_run(agent: AnalystAgent) -> _FakeRuns:
    runs = _FakeRuns()
    agent._agents_client = SimpleNamespace(runs=runs)
    agent._threads["session-1"] = AnalystThread(
        session_id="session-1",
        thread_id="thread-1",
    )
    return runs


@pytest.mark.asyncio
async def test_given_slow_analyst_when_timeout_expires_then_fallback_is_returned(
    monkeypatch,
) -> None:
    # Arrange
    agent = AnalystAgent()
    agent._run_timeout_seconds = 0.01
    runs = _attach_active_run(agent)

    async def never_finishes(_request):
        await asyncio.Event().wait()

    monkeypatch.setattr(agent, "_invoke_agent_service", never_finishes)

    # Act
    result = await agent.run(_request())

    # Assert
    assert result.structured["analyst_status"] == {
        "status": "timeout",
        "timeout_seconds": 0.01,
    }
    assert "timed out after 0.0s" in result.answer
    assert runs.cancelled == [("thread-1", "run-active")]
    assert "session-1" not in agent._threads
    assert get_session().session_id == "default"


@pytest.mark.asyncio
async def test_given_outer_cancellation_when_remote_run_is_active_then_run_is_cancelled(
    monkeypatch,
) -> None:
    # Arrange
    agent = AnalystAgent()
    agent._run_timeout_seconds = 60
    runs = _attach_active_run(agent)

    async def never_finishes(_request):
        await asyncio.Event().wait()

    monkeypatch.setattr(agent, "_invoke_agent_service", never_finishes)
    task = asyncio.create_task(agent.run(_request()))
    await asyncio.sleep(0)

    # Act
    task.cancel()

    # Assert
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runs.cancelled == [("thread-1", "run-active")]
    assert "session-1" not in agent._threads
    assert get_session().session_id == "default"


@pytest.mark.asyncio
async def test_given_slow_analysis_when_load_succeeded_then_load_result_is_preserved(
) -> None:
    # Arrange
    class SuccessfulLoad:
        async def run(self, _decision, _request, _body):
            return {
                "action": "LOAD",
                "answer": "Loading Ontario MODIS fire imagery.",
                "stac_query": "modis-14A1-061 Ontario July 2026",
                "structured": {"load_plan": {"action": "execute"}},
            }

    class SlowAnalyze:
        async def run(self, _decision, _request, _body):
            await asyncio.Event().wait()

    agent = LoadAndAnalyzeAgent(
        load_agent=SuccessfulLoad(),
        analyze_agent=SlowAnalyze(),
    )
    agent._analysis_timeout_seconds = 0.01
    decision = ActionDecision(
        action="LOAD_AND_ANALYZE",
        location="Ontario, Canada",
        analysis_question="How severe were the fires?",
    )

    # Act
    result = await agent.run(decision, _request(), {})

    # Assert
    assert result["action"] == "LOAD"
    assert result["stac_query"] == "modis-14A1-061 Ontario July 2026"
    assert result["structured"]["analysis_status"] == {
        "status": "timeout",
        "timeout_seconds": 0.01,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["timeout", "error"])
async def test_given_encoded_analyst_failure_when_load_succeeded_then_load_is_preserved(
    status,
) -> None:
    # Arrange
    class SuccessfulLoad:
        async def run(self, _decision, _request, _body):
            return {
                "action": "LOAD",
                "answer": "Loading Ontario MODIS fire imagery.",
                "stac_query": "modis-14A1-061 Ontario July 2026",
                "structured": {"load_plan": {"action": "execute"}},
            }

    class FailedAnalyze:
        async def run(self, _decision, _request, _body):
            return {
                "action": "LOAD_AND_ANALYZE",
                "answer": "Analysis fallback.",
                "structured": {"analyst_status": {"status": status}},
            }

    agent = LoadAndAnalyzeAgent(
        load_agent=SuccessfulLoad(),
        analyze_agent=FailedAnalyze(),
    )
    decision = ActionDecision(
        action="LOAD_AND_ANALYZE",
        location="Ontario, Canada",
        analysis_question="How severe were the fires?",
    )

    # Act
    result = await agent.run(decision, _request(), {})

    # Assert
    assert result["action"] == "LOAD"
    assert result["stac_query"] == "modis-14A1-061 Ontario July 2026"
    assert result["structured"]["analysis_status"] == {"status": status}