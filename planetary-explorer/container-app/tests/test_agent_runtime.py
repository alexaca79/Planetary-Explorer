"""Tests for the Microsoft Agent Framework prompt runtime."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from azure.identity import DefaultAzureCredential

from _framework.agent_runtime import AgentFrameworkRuntime


class _FakeAgent:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def run(
        self,
        prompt: str,
        *,
        options: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append((prompt, options))
        return self.response


class _FakeClient:
    def __init__(self, response: Any) -> None:
        self.agent = _FakeAgent(response)
        self.calls: list[dict[str, Any]] = []

    def as_agent(self, **kwargs: Any) -> _FakeAgent:
        self.calls.append(kwargs)
        return self.agent


@pytest.mark.parametrize("auth_mode", ["api_key", "managed_identity"])
def test_given_supported_auth_when_factory_runs_then_real_maf_provider_is_constructed(
    auth_mode: str,
) -> None:
    # Arrange
    credential = DefaultAzureCredential() if auth_mode == "managed_identity" else None
    auth = {"credential": credential} if credential else {"api_key": "test-key"}

    try:
        # Act
        runtime = AgentFrameworkRuntime.from_azure_openai(
            endpoint="https://example.openai.azure.com",
            primary_model="gpt-5",
            fast_model="gpt-4o-mini",
            **auth,
        )

        # Assert
        assert isinstance(runtime, AgentFrameworkRuntime)
    finally:
        if credential:
            credential.close()


@pytest.mark.asyncio
async def test_given_fast_tier_when_run_then_fast_client_receives_options() -> None:
    # Arrange
    primary = _FakeClient(SimpleNamespace(text="primary", value=None))
    fast = _FakeClient(SimpleNamespace(text="fast", value=None))
    runtime = AgentFrameworkRuntime(
        primary_client=primary,
        fast_client=fast,
        primary_model="gpt-5",
        fast_model="gpt-4o-mini",
    )

    # Act
    result = await runtime.run(
        "classify this",
        name="classifier",
        tier="fast",
        temperature=0.2,
        max_tokens=100,
    )

    # Assert
    assert result == "fast"
    assert fast.agent.calls == [
        ("classify this", {"temperature": 0.2, "max_tokens": 100})
    ]
    assert primary.calls == []


@pytest.mark.asyncio
async def test_given_restricted_model_when_run_then_sampling_options_are_removed() -> None:
    # Arrange
    primary = _FakeClient(SimpleNamespace(text="result", value=None))
    runtime = AgentFrameworkRuntime(
        primary_client=primary,
        fast_client=_FakeClient(SimpleNamespace(text="fast", value=None)),
        primary_model="gpt-5",
        fast_model="gpt-4o-mini",
    )

    # Act
    await runtime.run(
        "reason",
        name="reasoner",
        temperature=1.0,
        top_p=0.95,
        max_tokens=500,
    )

    # Assert
    assert primary.agent.calls == [("reason", {"max_tokens": 500})]


@pytest.mark.asyncio
async def test_given_structured_value_and_tool_when_run_then_json_and_tool_are_preserved() -> None:
    # Arrange
    client = _FakeClient(SimpleNamespace(text="", value={"location": "Seattle"}))
    runtime = AgentFrameworkRuntime(
        primary_client=client,
        fast_client=client,
        primary_model="gpt-4o",
        fast_model="gpt-4o-mini",
    )

    async def geocode(location: str) -> str:
        return location

    # Act
    result = await runtime.run(
        "find location",
        name="location_extractor",
        tier="fast",
        response_format={"type": "object"},
        tools=[geocode],
    )

    # Assert
    assert result == '{"location": "Seattle"}'
    assert client.calls[0]["tools"] == [geocode]