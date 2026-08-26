"""Microsoft Agent Framework runtime for one-shot prompt agents."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any, Literal, Protocol


AgentTier = Literal["primary", "fast"]


class _Agent(Protocol):
    async def run(
        self,
        prompt: str,
        *,
        options: dict[str, Any] | None = None,
    ) -> Any: ...


class _ChatClient(Protocol):
    def as_agent(
        self,
        *,
        name: str,
        instructions: str,
        tools: Callable[..., Any] | Sequence[Callable[..., Any]] | None = None,
    ) -> _Agent: ...


class AgentFrameworkRuntime:
    """Run short-lived MAF agents against primary and fast deployments."""

    _RESTRICTED_MODEL_MARKERS = ("gpt-5", "o1", "o3")

    def __init__(
        self,
        *,
        primary_client: _ChatClient,
        fast_client: _ChatClient,
        primary_model: str,
        fast_model: str,
    ) -> None:
        self._clients = {
            "primary": primary_client,
            "fast": fast_client,
        }
        self._models = {
            "primary": primary_model,
            "fast": fast_model,
        }

    @classmethod
    def from_azure_openai(
        cls,
        *,
        endpoint: str,
        primary_model: str,
        fast_model: str,
        api_key: str | None = None,
        credential: Any = None,
        api_version: str = "2024-10-21",
    ) -> "AgentFrameworkRuntime":
        """Create MAF Chat Completions clients for an Azure OpenAI endpoint."""
        if not endpoint:
            raise ValueError("Azure OpenAI endpoint is required")
        if not primary_model or not fast_model:
            raise ValueError("Primary and fast model deployments are required")
        if not api_key and credential is None:
            raise ValueError("Azure OpenAI API key or credential is required")

        from agent_framework.openai import OpenAIChatCompletionClient

        auth: dict[str, Any]
        if api_key:
            auth = {"api_key": api_key}
        else:
            auth = {"credential": credential}

        def create_client(model: str) -> _ChatClient:
            return OpenAIChatCompletionClient(
                model=model,
                azure_endpoint=endpoint,
                api_version=api_version,
                **auth,
            )

        return cls(
            primary_client=create_client(primary_model),
            fast_client=create_client(fast_model),
            primary_model=primary_model,
            fast_model=fast_model,
        )

    async def run(
        self,
        prompt: str,
        *,
        name: str,
        instructions: str = "Follow the request precisely and return only the requested output.",
        tier: AgentTier = "primary",
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        response_format: Any = None,
        tools: Callable[..., Any] | Sequence[Callable[..., Any]] | None = None,
    ) -> str:
        """Run one agent turn and return its text or structured value."""
        client = self._clients[tier]
        model = self._models[tier]
        options: dict[str, Any] = {}

        if not self._uses_restricted_options(model):
            if temperature is not None:
                options["temperature"] = temperature
            if top_p is not None:
                options["top_p"] = top_p
        if max_tokens is not None:
            options["max_tokens"] = max_tokens
        if response_format is not None:
            options["response_format"] = response_format

        agent = client.as_agent(
            name=name,
            instructions=instructions,
            tools=tools,
        )
        response = await agent.run(prompt, options=options or None)

        value = getattr(response, "value", None)
        if value is not None:
            if hasattr(value, "model_dump_json"):
                return value.model_dump_json()
            return json.dumps(value)
        return str(getattr(response, "text", response) or "")

    @classmethod
    def _uses_restricted_options(cls, model: str) -> bool:
        model_name = model.lower()
        return any(marker in model_name for marker in cls._RESTRICTED_MODEL_MARKERS)