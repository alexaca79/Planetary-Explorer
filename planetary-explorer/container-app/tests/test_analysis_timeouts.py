"""Bounded Analyst Agent behavior tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agents.analyst_agent.analyst_agent import (
    AnalystAgent,
    AnalystInvocation,
    AnalystThread,
)
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


def _publish_attached_thread(
    agent: AnalystAgent,
    invocation: AnalystInvocation,
) -> None:
    invocation.thread = agent._threads[invocation.session_id]
    invocation.owned_threads.append(invocation.thread)


async def _wait_for_remote_cancellation(
    agent: AnalystAgent,
    runs: _FakeRuns,
) -> None:
    for _ in range(20):
        if runs.cancelled and "session-1" not in agent._threads:
            return
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_given_slow_analyst_when_timeout_expires_then_fallback_is_returned(
    monkeypatch,
) -> None:
    # Arrange
    agent = AnalystAgent()
    agent._run_timeout_seconds = 0.01
    runs = _attach_active_run(agent)

    async def never_finishes(_request, invocation):
        _publish_attached_thread(agent, invocation)
        await asyncio.Event().wait()

    monkeypatch.setattr(agent, "_invoke_agent_service", never_finishes)

    # Act
    result = await agent.run(_request())
    await _wait_for_remote_cancellation(agent, runs)

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
async def test_given_slow_gpt_56_responses_when_timeout_expires_then_fallback_is_returned(
    monkeypatch,
) -> None:
    # Arrange
    agent = AnalystAgent()
    agent._run_timeout_seconds = 0.01

    async def never_finishes(_request, _invocation):
        await asyncio.Event().wait()

    monkeypatch.setattr(agent, "_invoke_responses_api", never_finishes)
    request = _request().model_copy(
        update={"model": "gpt-5.6-terra", "reasoning_effort": "high"}
    )

    # Act
    result = await asyncio.wait_for(agent.run(request), timeout=0.1)

    # Assert
    assert result.structured["analyst_status"] == {
        "status": "timeout",
        "timeout_seconds": 0.01,
    }
    assert get_session().session_id == "default"


@pytest.mark.asyncio
async def test_given_slow_geofm_preflight_when_timeout_expires_then_fallback_is_returned(
    monkeypatch,
) -> None:
    # Arrange
    import agents.analyst_agent.tools as analyst_tools

    agent = AnalystAgent()
    agent._run_timeout_seconds = 0.01

    async def never_finishes():
        await asyncio.Event().wait()

    monkeypatch.setattr(analyst_tools, "list_geofm_models", never_finishes)
    request = _request().model_copy(
        update={"geoint_module": "foundation_change"}
    )

    # Act
    result = await asyncio.wait_for(agent.run(request), timeout=0.1)

    # Assert
    assert result.structured["analyst_status"] == {
        "status": "timeout",
        "timeout_seconds": 0.01,
    }
    assert get_session().session_id == "default"


@pytest.mark.asyncio
async def test_given_outer_cancellation_when_remote_run_is_active_then_run_is_cancelled(
    monkeypatch,
) -> None:
    # Arrange
    agent = AnalystAgent()
    agent._run_timeout_seconds = 60
    runs = _attach_active_run(agent)

    async def never_finishes(_request, invocation):
        _publish_attached_thread(agent, invocation)
        await asyncio.Event().wait()

    monkeypatch.setattr(agent, "_invoke_agent_service", never_finishes)
    task = asyncio.create_task(agent.run(_request()))
    await asyncio.sleep(0)

    # Act
    task.cancel()

    # Assert
    with pytest.raises(asyncio.CancelledError):
        await task
    await _wait_for_remote_cancellation(agent, runs)
    assert runs.cancelled == [("thread-1", "run-active")]
    assert "session-1" not in agent._threads
    assert get_session().session_id == "default"


@pytest.mark.asyncio
async def test_given_cancellation_resistant_invocation_when_timeout_expires_then_response_is_bounded(
    monkeypatch,
) -> None:
    # Arrange
    agent = AnalystAgent()
    agent._run_timeout_seconds = 0.01
    runs = _attach_active_run(agent)
    release = asyncio.Event()

    async def resists_cancellation(_request, invocation):
        _publish_attached_thread(agent, invocation)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()

    monkeypatch.setattr(agent, "_invoke_agent_service", resists_cancellation)

    # Act
    result = await asyncio.wait_for(agent.run(_request()), timeout=0.1)

    # Assert
    try:
        await _wait_for_remote_cancellation(agent, runs)
        assert result.structured["analyst_status"]["status"] == "timeout"
        assert "session-1" not in agent._threads
    finally:
        release.set()
        for _ in range(20):
            if not agent._background_tasks:
                break
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_given_timeout_before_thread_publication_then_late_run_is_not_started(
    monkeypatch,
) -> None:
    # Arrange
    agent = AnalystAgent()
    agent._run_timeout_seconds = 0.01
    release = asyncio.Event()
    run_started = False

    async def publishes_late(_request, invocation):
        nonlocal run_started
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        invocation.thread = AnalystThread(
            session_id=invocation.session_id,
            thread_id="thread-late",
        )
        agent._threads[invocation.session_id] = invocation.thread
        if invocation.stop_requested:
            raise asyncio.CancelledError
        run_started = True

    monkeypatch.setattr(agent, "_invoke_agent_service", publishes_late)

    # Act
    result = await asyncio.wait_for(agent.run(_request()), timeout=0.1)
    try:
        release.set()
        for _ in range(100):
            if not agent._background_tasks:
                break
            await asyncio.sleep(0.01)

        # Assert
        assert result.structured["analyst_status"]["status"] == "timeout"
        assert run_started is False
        assert "session-1" not in agent._threads
    finally:
        release.set()


@pytest.mark.asyncio
async def test_given_overlapping_same_session_when_first_times_out_then_sibling_is_not_cancelled(
    monkeypatch,
) -> None:
    # Arrange
    agent = AnalystAgent()
    agent._run_timeout_seconds = 0.01
    first_release = asyncio.Event()
    sibling_started = asyncio.Event()
    call_count = 0

    async def serialized_invocation(_request, invocation):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            await first_release.wait()
            if invocation.stop_requested:
                raise asyncio.CancelledError
        sibling_started.set()
        return "sibling answer", [], []

    monkeypatch.setattr(agent, "_invoke_agent_service", serialized_invocation)
    first = asyncio.create_task(agent.run(_request()))
    await asyncio.sleep(0)
    agent._run_timeout_seconds = 0.2
    sibling = asyncio.create_task(agent.run(_request()))

    # Act
    first_result = await asyncio.wait_for(first, timeout=0.1)
    first_release.set()
    await sibling_started.wait()
    sibling_result = await asyncio.wait_for(sibling, timeout=0.1)

    # Assert
    assert first_result.structured["analyst_status"]["status"] == "timeout"
    assert sibling_result.answer == "sibling answer"


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
async def test_given_cancellation_resistant_analysis_when_timeout_expires_then_load_returns(
) -> None:
    # Arrange
    release = asyncio.Event()

    class SuccessfulLoad:
        async def run(self, _decision, _request, _body):
            return {
                "action": "LOAD",
                "answer": "Loading Ontario MODIS fire imagery.",
                "stac_query": "modis-14A1-061 Ontario July 2026",
                "structured": {"load_plan": {"action": "execute"}},
            }

    class CancellationResistantAnalyze:
        async def run(self, _decision, _request, _body):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()

    agent = LoadAndAnalyzeAgent(
        load_agent=SuccessfulLoad(),
        analyze_agent=CancellationResistantAnalyze(),
    )
    agent._analysis_timeout_seconds = 0.01
    decision = ActionDecision(
        action="LOAD_AND_ANALYZE",
        location="Ontario, Canada",
        analysis_question="How severe were the fires?",
    )

    # Act
    result = await asyncio.wait_for(
        agent.run(decision, _request(), {}),
        timeout=0.1,
    )

    # Assert
    assert result["action"] == "LOAD"
    assert result["structured"]["analysis_status"]["status"] == "timeout"
    release.set()
    await asyncio.sleep(0)


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