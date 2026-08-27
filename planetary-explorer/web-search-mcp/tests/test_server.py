"""MCP protocol and tool tests for Azure Web Search."""

from datetime import UTC, datetime

import anyio
import pytest
from starlette.testclient import TestClient

import web_search_mcp.server as server_module
from web_search_mcp.server import (
    _normalize_search_response,
    build_app,
    get_current_datetime,
    mcp,
    readiness,
    web_search,
)

HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "X-API-Key": "test-web-search-key-32-characters!",
}


class FakeResponse:
    """Minimal Responses API result used by normalization tests."""

    output_text = "Today is August 26, 2026."

    def model_dump(self, *, mode: str) -> dict:
        assert mode == "json"
        return {
            "output": [
                {
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {
                        "sources": [
                            {"type": "url", "url": "https://example.com/time"}
                        ]
                    },
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": self.output_text,
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "title": "Example Time",
                                    "url": "https://example.com/time",
                                }
                            ],
                        }
                    ],
                },
            ]
        }


def test_given_server_when_listing_tools_then_read_only_surface_is_complete() -> None:
    # Act
    tools = anyio.run(mcp.list_tools)

    # Assert
    assert {tool.name for tool in tools} == {"get_current_datetime", "web_search"}
    assert all(tool.annotations.readOnlyHint for tool in tools)


def test_given_utc_clock_when_requested_then_current_date_is_returned() -> None:
    # Arrange
    before = datetime.now(UTC)

    # Act
    result = anyio.run(get_current_datetime)
    after = datetime.now(UTC)

    # Assert
    assert before.date() <= datetime.fromisoformat(result.iso8601).date() <= after.date()
    assert result.timezone == "UTC"


def test_given_unknown_timezone_when_requested_then_value_error_is_raised() -> None:
    # Act & Assert
    with pytest.raises(ValueError, match="Unknown IANA timezone"):
        anyio.run(get_current_datetime, "Mars/Olympus_Mons")


def test_given_foundry_response_when_normalized_then_answer_and_citations_are_preserved() -> None:
    # Act
    result = _normalize_search_response("what is today", FakeResponse())

    # Assert
    assert result.answer == "Today is August 26, 2026."
    assert result.citations[0].url == "https://example.com/time"
    assert result.source_urls == ["https://example.com/time"]


def test_given_query_when_searching_then_foundry_web_search_is_required(monkeypatch) -> None:
    # Arrange
    calls: list[tuple[str, str]] = []

    async def fake_search(query: str, context_size: str):
        calls.append((query, context_size))
        return FakeResponse()

    monkeypatch.setattr(server_module, "_run_foundry_web_search", fake_search)

    # Act
    result = anyio.run(web_search, " current date ", "low")

    # Assert
    assert calls == [("current date", "low")]
    assert result.provider == "Microsoft Foundry Web Search"


def test_given_required_protocol_methods_when_called_then_each_returns_http_success(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "FOUNDRY_PROJECT_ENDPOINT",
        "https://example.services.ai.azure.com/api/projects/planetary",
    )
    monkeypatch.setenv("FOUNDRY_MODEL", "gpt-4o")
    monkeypatch.setenv("WEB_SEARCH_MCP_API_KEY", HEADERS["X-API-Key"])
    calls = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "web-search-contract-test", "version": "1.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "prompts/list", "params": {}},
        {"jsonrpc": "2.0", "id": 4, "method": "resources/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "logging/setLevel",
            "params": {"level": "info"},
        },
    ]

    # Act
    with TestClient(build_app()) as client:
        health_status = client.get("/health").status_code
        ready_status = client.get("/ready").status_code
        missing_key_status = client.post(
            "/mcp",
            headers={key: value for key, value in HEADERS.items() if key != "X-API-Key"},
            json=calls[2],
        ).status_code
        invalid_key_status = client.post(
            "/mcp",
            headers={**HEADERS, "X-API-Key": "wrong"},
            json=calls[2],
        ).status_code
        statuses = [
            client.post("/mcp", headers=HEADERS, json=call).status_code
            for call in calls
        ]

    # Assert
    assert health_status == 200
    assert ready_status == 200
    assert missing_key_status == 401
    assert invalid_key_status == 401
    assert statuses == [200, 200, 200, 200, 200, 200]


@pytest.mark.parametrize("api_key", ["", "too-short"])
def test_given_missing_or_short_api_key_when_checking_readiness_then_service_is_degraded(
    monkeypatch,
    api_key: str,
) -> None:
    # Arrange
    monkeypatch.setenv(
        "FOUNDRY_PROJECT_ENDPOINT",
        "https://example.services.ai.azure.com/api/projects/planetary",
    )
    monkeypatch.setenv("FOUNDRY_MODEL", "gpt-4o")
    monkeypatch.setenv("WEB_SEARCH_MCP_API_KEY", api_key)

    # Act
    response = anyio.run(readiness)

    # Assert
    assert response.status_code == 503
