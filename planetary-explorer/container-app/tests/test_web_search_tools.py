"""AnalystAgent Azure Web Search MCP routing tests."""

from __future__ import annotations

import pytest

from agents.analyst_agent import tools as analyst_tools
from agents.analyst_agent.analyst_prompt import ANALYST_AGENT_INSTRUCTIONS
from agents.analyst_agent.session_context import AnalystSession, clear_session, set_session
from mcp_runtime.registry import McpRegistry, get_registry
from mcp_runtime.traced_client import TracedMcpClient


class FakeWebSearchClient:
    """Capture analyst calls and return deterministic MCP payloads."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool: str, arguments: dict):
        self.calls.append((tool, arguments))
        if tool == "get_current_datetime":
            return {
                "date": "2026-08-26",
                "time": "15:00:00+00:00",
                "iso8601": "2026-08-26T15:00:00+00:00",
                "timezone": "UTC",
                "weekday": "Wednesday",
            }
        return {
            "query": arguments["query"],
            "answer": "A cited current answer.",
            "citations": [
                {"title": "Current source", "url": "https://example.com/current"}
            ],
        }


@pytest.fixture(autouse=True)
def analyst_session():
    set_session(AnalystSession(session_id="web-search-test"))
    yield
    clear_session()
    get_registry.cache_clear()


@pytest.mark.asyncio
async def test_given_current_date_question_when_clock_called_then_mcp_value_is_returned(
    monkeypatch,
) -> None:
    # Arrange
    fake = FakeWebSearchClient()
    monkeypatch.setattr(
        TracedMcpClient,
        "from_web_search",
        classmethod(lambda cls, **_kwargs: fake),
    )

    # Act
    result = await analyst_tools.get_current_datetime()

    # Assert
    assert result["structured"]["date"] == "2026-08-26"
    assert fake.calls == [("get_current_datetime", {"timezone": "UTC"})]


@pytest.mark.asyncio
async def test_given_current_fact_question_when_search_called_then_citations_are_preserved(
    monkeypatch,
) -> None:
    # Arrange
    fake = FakeWebSearchClient()
    monkeypatch.setattr(
        TracedMcpClient,
        "from_web_search",
        classmethod(lambda cls, **_kwargs: fake),
    )

    # Act
    result = await analyst_tools.search_web("latest wildfire status", "low")

    # Assert
    assert result["answer"] == "A cited current answer."
    assert result["sources"][0]["uri"] == "https://example.com/current"
    assert fake.calls == [
        (
            "web_search",
            {"query": "latest wildfire status", "search_context_size": "low"},
        )
    ]


def test_given_web_search_environment_when_registry_discovered_then_server_is_enabled(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")
    monkeypatch.setenv("WEB_SEARCH_MCP_URL", "https://web-search.internal/mcp")

    # Act
    registry = McpRegistry.discover()

    # Assert
    server = registry.get("web_search")
    assert server is not None
    assert server.url == "https://web-search.internal/mcp"


def test_given_web_search_environment_when_client_built_then_tracing_is_enabled(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")
    monkeypatch.setenv("WEB_SEARCH_MCP_URL", "https://web-search.internal/mcp")
    get_registry.cache_clear()

    # Act
    client = TracedMcpClient.from_web_search(turn_id="web-search-turn")

    # Assert
    assert client is not None
    assert client.server_id == "web_search"
    assert client.turn_id == "web-search-turn"


def test_given_analyst_prompt_when_read_then_current_date_cannot_use_model_memory() -> None:
    # Assert
    assert "ALWAYS call ``get_current_datetime``" in ANALYST_AGENT_INSTRUCTIONS
    assert "current/latest/recent public information" in ANALYST_AGENT_INSTRUCTIONS
    assert "do not guess" in ANALYST_AGENT_INSTRUCTIONS


def test_given_analyst_registry_when_created_then_web_tools_are_registered() -> None:
    # Act
    names = {function.__name__ for function in analyst_tools.create_analyst_functions()}

    # Assert
    assert {"get_current_datetime", "search_web"} <= names