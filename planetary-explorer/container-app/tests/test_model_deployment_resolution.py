"""Configured model deployment routing tests."""

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def test_given_unavailable_requested_model_when_resolving_then_request_is_rejected(
    monkeypatch,
) -> None:
    # Arrange
    import fastapi_app

    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")

    # Act
    with pytest.raises(HTTPException, match="unavailable") as error:
        fastapi_app._resolve_chat_deployment("gpt-5")

    # Assert
    assert error.value.status_code == 400


def test_given_no_requested_model_when_resolving_then_configured_model_is_used(
    monkeypatch,
) -> None:
    # Arrange
    import fastapi_app

    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")

    # Act and assert
    assert fastapi_app._resolve_chat_deployment(None) == "gpt-4o"


@pytest.mark.asyncio
async def test_given_configured_model_when_health_requested_then_model_is_advertised(
    monkeypatch,
) -> None:
    # Arrange
    import fastapi_app

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class FakeSession:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def get(self, _url):
            return FakeResponse()

    async def fake_geofm_health():
        return {
            "enabled": False,
            "connected": False,
            "status": "disabled",
            "tool_count": 0,
            "tools": [],
            "models": [],
        }

    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")
    monkeypatch.setenv(
        "AZURE_OPENAI_AVAILABLE_MODELS",
        "gpt-4o,gpt-5.6-sol,gpt-5.6-terra,gpt-5.6-luna,text-embedding-3-small",
    )
    monkeypatch.setenv("USE_MANAGED_IDENTITY", "true")
    monkeypatch.setenv("AZURE_MAPS_KEY", "configured")
    monkeypatch.setattr(fastapi_app.aiohttp, "ClientSession", FakeSession)
    monkeypatch.setattr(fastapi_app, "get_health_snapshot", fake_geofm_health)

    # Act
    response = await fastapi_app.health_check()
    payload = json.loads(response.body)

    # Assert
    assert response.status_code == 200
    assert payload["checks"]["azure_openai"]["model"] == "gpt-4o"
    assert payload["checks"]["azure_openai"]["available_models"] == [
        "gpt-4o",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    ]
    assert payload["checks"]["azure_openai"]["model_capabilities"]["gpt-5.6-sol"] == {
        "reasoning_efforts": ["none", "low", "medium", "high", "xhigh", "max"],
        "default_reasoning_effort": "medium",
    }


def test_given_available_gpt_56_model_when_resolving_then_requested_model_wins(
    monkeypatch,
) -> None:
    # Arrange
    import fastapi_app

    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")
    monkeypatch.setenv("AZURE_OPENAI_AVAILABLE_MODELS", "gpt-4o,gpt-5.6-sol")

    # Act and assert
    assert fastapi_app._resolve_chat_deployment("gpt-5.6-sol") == "gpt-5.6-sol"


@pytest.mark.parametrize("effort", ["none", "low", "medium", "high", "xhigh", "max"])
def test_given_gpt_56_model_when_resolving_effort_then_all_supported_levels_work(
    effort,
) -> None:
    # Arrange
    import fastapi_app

    # Act and assert
    assert fastapi_app._resolve_reasoning_effort("gpt-5.6-terra", effort) == effort


def test_given_unsupported_effort_when_resolving_then_request_is_rejected() -> None:
    # Arrange
    import fastapi_app

    # Act
    with pytest.raises(HTTPException, match="unsupported") as error:
        fastapi_app._resolve_reasoning_effort("gpt-5.6-luna", "minimal")

    # Assert
    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_given_gpt_56_turn_when_analyzing_then_responses_uses_selected_effort(
    monkeypatch,
) -> None:
    # Arrange
    from agents.analyst_agent.analyst_agent import AnalystAgent
    from pipeline.contracts import AnalysisRequest

    class FakeResponses:
        def __init__(self) -> None:
            self.calls = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                id="response-1",
                output=[],
                output_text="GPT-5.6 answer",
            )

    class FakeClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    fake_client = FakeClient()
    agent = AnalystAgent()

    async def fake_create_responses_client():
        return fake_client, None

    async def unexpected_agent_service(*_args):
        raise AssertionError("GPT-5.6 must not use the persisted Agent Service path")

    monkeypatch.setattr(agent, "_create_responses_client", fake_create_responses_client)
    monkeypatch.setattr(agent, "_invoke_agent_service", unexpected_agent_service)
    request = AnalysisRequest(
        question="Explain the loaded imagery",
        session_id="gpt-56-test",
        model="gpt-5.6-luna",
        reasoning_effort="max",
    )

    # Act
    result = await agent.run(request)

    # Assert
    assert result.answer == "GPT-5.6 answer"
    assert fake_client.responses.calls[0]["model"] == "gpt-5.6-luna"
    assert fake_client.responses.calls[0]["reasoning"] == {"effort": "max"}
    assert fake_client.closed is True


@pytest.mark.asyncio
async def test_given_gpt_56_tool_call_when_analyzing_then_output_is_continued_with_evidence(
    monkeypatch,
) -> None:
    # Arrange
    import agents.analyst_agent.tools as analyst_tools
    from agents.analyst_agent.analyst_agent import AnalystAgent
    from agents.analyst_agent.session_context import get_session
    from pipeline.contracts import AnalysisRequest

    async def inspect_scene(scene_id: str) -> dict:
        """Inspect one loaded scene."""
        result = {"success": True, "scene_id": scene_id}
        get_session().evidence.append({"tool": "inspect_scene", "payload": result})
        return result

    class FakeResponses:
        def __init__(self) -> None:
            self.calls = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return SimpleNamespace(
                    id="response-tool",
                    output=[
                        SimpleNamespace(
                            type="function_call",
                            name="inspect_scene",
                            arguments='{"scene_id": "scene-1"}',
                            call_id="call-1",
                        )
                    ],
                    output_text="",
                )
            return SimpleNamespace(
                id="response-final",
                output=[],
                output_text="Scene inspection complete.",
            )

    class FakeClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()

        async def close(self) -> None:
            return None

    fake_client = FakeClient()
    agent = AnalystAgent()

    async def fake_create_responses_client():
        return fake_client, None

    monkeypatch.setattr(
        analyst_tools,
        "create_analyst_functions",
        lambda: [inspect_scene],
    )
    monkeypatch.setattr(agent, "_create_responses_client", fake_create_responses_client)
    request = AnalysisRequest(
        question="Inspect scene one",
        session_id="gpt-56-tool-test",
        model="gpt-5.6-sol",
        reasoning_effort="high",
    )

    # Act
    result = await agent.run(request)

    # Assert
    continuation = fake_client.responses.calls[1]
    assert result.answer == "Scene inspection complete."
    assert [step.analyzer for step in result.plan.steps] == ["inspect_scene"]
    assert continuation["previous_response_id"] == "response-tool"
    assert continuation["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": '{"success": true, "scene_id": "scene-1"}',
        }
    ]


@pytest.mark.asyncio
async def test_given_eight_tool_rounds_when_final_response_arrives_then_answer_is_returned(
    monkeypatch,
) -> None:
    # Arrange
    import agents.analyst_agent.tools as analyst_tools
    from agents.analyst_agent.analyst_agent import AnalystAgent
    from agents.analyst_agent.session_context import get_session
    from pipeline.contracts import AnalysisRequest

    async def advance() -> dict:
        """Advance one bounded analysis step."""
        result = {"success": True}
        get_session().evidence.append({"tool": "advance", "payload": result})
        return result

    class FakeResponses:
        def __init__(self) -> None:
            self.calls = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) <= 8:
                round_number = len(self.calls)
                return SimpleNamespace(
                    id=f"response-{round_number}",
                    output=[
                        SimpleNamespace(
                            type="function_call",
                            name="advance",
                            arguments="{}",
                            call_id=f"call-{round_number}",
                        )
                    ],
                    output_text="",
                )
            return SimpleNamespace(
                id="response-final",
                output=[],
                output_text="Eight rounds complete.",
            )

    class FakeClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()

        async def close(self) -> None:
            return None

    fake_client = FakeClient()
    agent = AnalystAgent()

    async def fake_create_responses_client():
        return fake_client, None

    monkeypatch.setattr(analyst_tools, "create_analyst_functions", lambda: [advance])
    monkeypatch.setattr(agent, "_create_responses_client", fake_create_responses_client)
    request = AnalysisRequest(
        question="Complete eight analysis steps",
        session_id="gpt-56-eight-round-test",
        model="gpt-5.6-terra",
        reasoning_effort="high",
    )

    # Act
    result = await agent.run(request)

    # Assert
    assert result.answer == "Eight rounds complete."
    assert len(fake_client.responses.calls) == 9
    assert [step.analyzer for step in result.plan.steps] == ["advance"] * 8