"""Reusable Streamable HTTP client for internal MCP services."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)


class RemoteMcpUnavailable(RuntimeError):
    """Raised when a configured remote MCP service cannot satisfy a call."""


class RemoteMcpClient:
    """Task-scoped Streamable HTTP MCP client facade."""

    def __init__(
        self,
        url: str,
        *,
        api_key: str | None = None,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        raw_url = url.strip().rstrip("/")
        self._url = raw_url[: -len("/mcp")] if raw_url.endswith("/mcp") else raw_url
        self._api_key = api_key
        self._request_timeout = request_timeout_seconds
        self._available_tools: set[str] = set()

    @property
    def configured(self) -> bool:
        """Return whether a non-empty remote URL was supplied."""
        return bool(self._url)

    @property
    def available_tools(self) -> tuple[str, ...]:
        """Return the tool names advertised by the active MCP session."""
        return tuple(sorted(self._available_tools))

    async def call_raw(self, tool: str, arguments: dict[str, Any]) -> Any:
        """Invoke one advertised tool and unwrap its structured response."""
        try:
            async with asyncio.timeout(self._request_timeout):
                stack, session = await self._open_session()
        except TimeoutError as exc:
            raise RemoteMcpUnavailable("Remote MCP session initialization timed out.") from exc

        try:
            if self._available_tools and tool not in self._available_tools:
                raise RemoteMcpUnavailable(
                    f"Remote MCP tool '{tool}' is not advertised by the configured service."
                )
            async with asyncio.timeout(self._request_timeout):
                result = await session.call_tool(tool, arguments)
        except TimeoutError as exc:
            raise RemoteMcpUnavailable(f"Remote MCP tool '{tool}' timed out.") from exc
        except RemoteMcpUnavailable:
            raise
        except Exception as exc:
            raise RemoteMcpUnavailable(f"Remote MCP tool '{tool}' failed: {exc}") from exc
        finally:
            await stack.aclose()

        if getattr(result, "isError", False):
            raise RemoteMcpUnavailable(f"Remote MCP tool '{tool}' returned an error.")
        structured = getattr(result, "structuredContent", None)
        if structured:
            return structured
        for item in getattr(result, "content", ()):
            text = getattr(item, "text", None)
            if not text:
                continue
            try:
                return json.loads(text)
            except (TypeError, ValueError):
                return text
        return None

    async def close(self) -> None:
        """Clear cached discovery metadata; calls own their transports."""
        self._available_tools = set()

    async def _open_session(self) -> tuple[AsyncExitStack, ClientSession]:
        if not self.configured:
            raise RemoteMcpUnavailable("Remote MCP URL is not configured.")

        headers = {"X-API-Key": self._api_key} if self._api_key else None
        stack = AsyncExitStack()
        try:
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(
                    url=f"{self._url}/mcp",
                    headers=headers,
                )
            )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            tools = await session.list_tools()
            self._available_tools = {tool.name for tool in tools.tools}
            logger.info(
                "[MCP] connected to %s with %d advertised tools",
                self._url,
                len(self._available_tools),
            )
            return stack, session
        except asyncio.CancelledError:
            await stack.aclose()
            raise
        except Exception as exc:
            await stack.aclose()
            raise RemoteMcpUnavailable(
                f"Remote MCP session initialization failed: {exc}"
            ) from exc