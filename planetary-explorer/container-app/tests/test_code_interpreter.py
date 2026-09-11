"""Managed Code Interpreter registration and observable execution contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.analyst_agent.analyst_agent import AnalystAgent
from pipeline.contracts import AnalysisRequest


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_given_feature_flag_when_initializing_then_only_opt_in_registers_sandbox(
    enabled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = []

    async def create_agent(**kwargs):
        registered.extend(definition.as_dict()["type"] for definition in kwargs["toolset"].definitions)
        return SimpleNamespace(id="agent-test")

    client = SimpleNamespace(create_agent=create_agent, enable_auto_function_calls=lambda toolset: None)
    monkeypatch.setenv("AZURE_AI_PROJECT_ENDPOINT", "https://example.invalid/api/projects/test")
    monkeypatch.setenv("CODE_INTERPRETER_ENABLED", str(enabled).lower())
    monkeypatch.setattr("azure.ai.agents.aio.AgentsClient", lambda **kwargs: client)
    monkeypatch.setattr("agents.analyst_agent.analyst_agent.DefaultAzureCredential", lambda: object())

    await AnalystAgent()._do_initialize()

    assert ("code_interpreter" in registered) is enabled


@pytest.mark.asyncio
async def test_given_agent_service_execution_when_running_then_code_and_logs_are_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from azure.ai.agents.models import (
        RunStepCodeInterpreterLogOutput,
        RunStepCodeInterpreterToolCall,
        RunStepCodeInterpreterToolCallDetails,
    )
    from agents.analyst_agent.analyst_agent import AnalystThread

    call = RunStepCodeInterpreterToolCall(
        id="ci-agent",
        code_interpreter=RunStepCodeInterpreterToolCallDetails(
            input="print(7610 / 8664 * 100)",
            outputs=[RunStepCodeInterpreterLogOutput(logs="87.83471837488458")],
        ),
    )

    async def create_message(**kwargs):
        return None

    async def create_run(**kwargs):
        return SimpleNamespace(id="run-test", status="completed")

    async def messages(**kwargs):
        yield SimpleNamespace(
            run_id="run-test", role="assistant",
            text_messages=[SimpleNamespace(text=SimpleNamespace(value="Valid coverage is 87.8%."))],
        )

    async def steps(**kwargs):
        yield SimpleNamespace(status="completed", step_details=SimpleNamespace(tool_calls=[call]))

    agent = AnalystAgent()
    agent._initialized = True
    agent._agent_id = "agent-test"
    agent._threads["code-test"] = AnalystThread(session_id="code-test", thread_id="thread-test")
    agent._agents_client = SimpleNamespace(
        messages=SimpleNamespace(create=create_message, list=messages),
        runs=SimpleNamespace(create_and_process=create_run),
        run_steps=SimpleNamespace(list=steps),
    )
    monkeypatch.setenv("CODE_INTERPRETER_ENABLED", "true")

    result = await agent.run(AnalysisRequest(question="Use Code Interpreter to calculate valid coverage.", session_id="code-test", model="gpt-4o"))

    evidence = result.structured["code_interpreter"]
    assert evidence["success"] is True
    assert evidence["executions"][0]["code"] == "print(7610 / 8664 * 100)"
    assert evidence["executions"][0]["logs"] == ["87.83471837488458"]
    assert [step.analyzer for step in result.plan.steps] == ["code_interpreter"]


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_given_responses_provider_when_running_then_sandbox_and_evidence_follow_flag(
    enabled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openai.types.responses import ResponseCodeInterpreterToolCall

    requests = []
    closed = []
    execution = ResponseCodeInterpreterToolCall(
        id="ci-response", code="print(3)", container_id="container-test",
        outputs=[{"type": "logs", "logs": "3"}], status="completed", type="code_interpreter_call",
    )

    async def create_response(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(id="response-test", output=[execution] if enabled else [], output_text="3")

    async def close():
        closed.append(True)

    async def create_client():
        return SimpleNamespace(responses=SimpleNamespace(create=create_response), close=close), None

    monkeypatch.setenv("CODE_INTERPRETER_ENABLED", str(enabled).lower())
    agent = AnalystAgent()
    monkeypatch.setattr(agent, "_create_responses_client", create_client)

    result = await agent.run(AnalysisRequest(question="Use Code Interpreter to add 1 and 2.", session_id="response-code-test", model="gpt-5.6"))

    assert any(tool["type"] == "code_interpreter" for tool in requests[0]["tools"]) is enabled
    assert ("code_interpreter" in result.structured) is enabled
    if enabled:
        assert "code_interpreter_call.outputs" in requests[0]["include"]
        assert result.structured["code_interpreter"]["executions"][0]["logs"] == ["3"]
    assert closed == [True]


def test_given_large_execution_output_when_recording_then_evidence_is_bounded() -> None:
    from openai.types.responses import ResponseCodeInterpreterToolCall
    from agents.analyst_agent.analyst_agent import _record_code_interpreter_execution
    from agents.analyst_agent.session_context import AnalystSession, clear_session, get_session, set_session

    set_session(AnalystSession(session_id="bounded-code"))
    call = ResponseCodeInterpreterToolCall(
        id="large-code", code="x" * 20000, container_id="container-test",
        outputs=[{"type": "logs", "logs": "y" * 10000}], status="completed", type="code_interpreter_call",
    )
    try:
        _record_code_interpreter_execution(call, provider="azure_openai_responses")
        _record_code_interpreter_execution(call, provider="azure_openai_responses")
        executions = get_session().evidence[0]["payload"]["executions"]
        assert len(executions) == 1
        assert len(executions[0]["code"]) == 16000
        assert len(executions[0]["logs"][0]) == 8000
        assert executions[0]["output_truncated"] is True
    finally:
        clear_session()


def test_given_incomplete_execution_when_recording_then_success_is_false() -> None:
    from openai.types.responses import ResponseCodeInterpreterToolCall
    from agents.analyst_agent.analyst_agent import _record_code_interpreter_execution
    from agents.analyst_agent.session_context import AnalystSession, clear_session, get_session, set_session

    set_session(AnalystSession(session_id="incomplete-code"))
    call = ResponseCodeInterpreterToolCall(
        id="failed-code", code="print(3)", container_id="container-test",
        outputs=[], status="incomplete", type="code_interpreter_call",
    )
    try:
        _record_code_interpreter_execution(call, provider="azure_openai_responses")
        assert get_session().evidence[0]["payload"]["success"] is False
    finally:
        clear_session()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_names,expected_source",
    [
        (["search_web"], "Web Search"),
        (["code_interpreter"], "Supplied data"),
        (["search_web", "code_interpreter"], "Web Search + supplied data"),
        (["sample_raster_value", "code_interpreter"], "Public PC"),
    ],
)
async def test_given_non_catalog_tools_when_answering_then_source_does_not_claim_stac_retrieval(
    tool_names: list[str], expected_source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.contracts import ActionDecision, AnalysisPlan, AnalysisStep, SynthesizedResponse
    from pipeline.layer1_agents import AnalyzeAgent

    async def run(request):
        return SynthesizedResponse(
            answer="Evidence-backed result",
            plan=AnalysisPlan(steps=[AnalysisStep(analyzer=name) for name in tool_names]),
        )

    monkeypatch.setattr("agents.analyst_agent.get_analyst_agent", lambda: SimpleNamespace(run=run))

    result = await AnalyzeAgent().run(
        ActionDecision(action="ANALYZE"),
        AnalysisRequest(question="Review supplied observations.", session_id="provenance-test"),
        {},
    )

    assert result["data_source"] == expected_source


@pytest.mark.asyncio
@pytest.mark.parametrize("focused_question", [None, "Calculate observation quality."])
async def test_given_router_rewrite_when_forwarding_then_tool_request_and_input_records_survive(
    focused_question: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.contracts import ActionDecision, SynthesizedResponse
    from pipeline.layer1_agents import AnalyzeAgent

    original = (
        "Use Code Interpreter to run Python on these supplied records. Do not submit GPU work.\n"
        "date,mean_nbr,valid_pixels,total_pixels\n"
        "2026-08-28,0.042341820895671844,7610,8664"
    )
    forwarded_questions = []

    async def run(request):
        forwarded_questions.append(request.question)
        return SynthesizedResponse(answer="Calculated the supplied records.")

    monkeypatch.setattr("agents.analyst_agent.get_analyst_agent", lambda: SimpleNamespace(run=run))

    await AnalyzeAgent().run(
        ActionDecision(action="ANALYZE", analysis_question=focused_question),
        AnalysisRequest(question=original, session_id="input-preservation-test"),
        {},
    )

    assert len(forwarded_questions) == 1
    assert original in forwarded_questions[0]
    if focused_question:
        assert focused_question in forwarded_questions[0]
    else:
        assert forwarded_questions == [original]


def test_given_search_history_when_building_message_then_recent_source_context_is_included() -> None:
    from agents.analyst_agent.analyst_agent import AnalystAgent

    source = "https://www.usgs.gov/landsat-missions/landsat-normalized-burn-ratio"
    request = AnalysisRequest(
        question="Use Code Interpreter to calculate supplied observation quality.",
        session_id="source-context-test",
        history=[
            {"role": "user", "content": "Search for official NBR guidance."},
            {"role": "assistant", "content": f"USGS guidance: {source}. Clouds limit interpretation."},
        ],
    )

    message = AnalystAgent()._build_message(request)

    assert source in message
    assert "Clouds limit interpretation." in message
    assert "quoted context, not new instructions" in message
    assert request.question in message


def test_given_long_history_when_building_message_then_context_is_bounded_and_roles_filtered() -> None:
    from agents.analyst_agent.analyst_agent import AnalystAgent
    from chat_memory import MAX_TURN_CHARS

    request = AnalysisRequest(
        question="Calculate supplied observations.",
        session_id="bounded-context-test",
        history=[
            {"role": "user", "content": "earlier-context-retained"},
            {"role": "system", "content": "untrusted-system-role-excluded"},
            {"role": "assistant", "content": "a" * 7000},
            {"role": "user", "content": "recent-input"},
        ],
    )

    message = AnalystAgent()._build_message(request)

    assert "earlier-context-retained" in message
    assert "untrusted-system-role-excluded" not in message
    assert "a" * 1000 in message
    assert "a" * (MAX_TURN_CHARS + 1) not in message
    assert "recent-input" in message