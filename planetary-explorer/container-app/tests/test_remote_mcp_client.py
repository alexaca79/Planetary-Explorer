"""Remote MCP transport lifecycle tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import mcp_runtime.remote_client as remote_client_module
from mcp_runtime.remote_client import RemoteMcpClient
from mcp_runtime.remote_client import RemoteMcpUnavailable


class _TaskBoundContext:
    """Fail when an async context exits from a task other than its owner."""

    def __init__(self, value) -> None:
        self._value = value
        self._owner = None

    async def __aenter__(self):
        self._owner = asyncio.current_task()
        return self._value

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        assert asyncio.current_task() is self._owner


class _FakeSession(_TaskBoundContext):
    def __init__(self, _read, _write) -> None:
        super().__init__(self)

    async def initialize(self) -> None:
        return None

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name="geofm_list_models")])

    async def call_tool(self, _tool, _arguments):
        return SimpleNamespace(
            isError=False,
            structuredContent={"payload": {"models": []}},
            content=[],
        )


class _BlockingSession(_FakeSession):
    exited = False

    async def initialize(self) -> None:
        await asyncio.Event().wait()

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        type(self).exited = True
        await super().__aexit__(_exc_type, _exc, _traceback)


class _CancellationResistantExitSession(_FakeSession):
    release = asyncio.Event()

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        try:
            await type(self).release.wait()
        except asyncio.CancelledError:
            await type(self).release.wait()


@pytest.mark.asyncio
async def test_given_task_bound_transport_when_closed_then_owner_task_is_preserved(
    monkeypatch,
) -> None:
    # Arrange
    monkeypatch.setattr(
        remote_client_module,
        "streamable_http_client",
        lambda **_kwargs: _TaskBoundContext((object(), object(), None)),
    )
    monkeypatch.setattr(remote_client_module, "ClientSession", _FakeSession)
    client = RemoteMcpClient("https://geofm.example", request_timeout_seconds=1)

    # Act
    result = await client.call_raw("geofm_list_models", {})
    await client.close()

    # Assert
    assert result == {"payload": {"models": []}}


@pytest.mark.asyncio
async def test_given_initialization_timeout_when_contexts_entered_then_stack_is_closed(
    monkeypatch,
) -> None:
    # Arrange
    transport = _TaskBoundContext((object(), object(), None))
    _BlockingSession.exited = False
    monkeypatch.setattr(
        remote_client_module,
        "streamable_http_client",
        lambda **_kwargs: transport,
    )
    monkeypatch.setattr(remote_client_module, "ClientSession", _BlockingSession)
    client = RemoteMcpClient("https://geofm.example", request_timeout_seconds=0.01)

    # Act & Assert
    with pytest.raises(RemoteMcpUnavailable, match="timed out"):
        await client.call_raw("geofm_list_models", {})
    if client._active_task is not None:
        await asyncio.gather(client._active_task, return_exceptions=True)
    assert _BlockingSession.exited is True


@pytest.mark.asyncio
async def test_given_cancellation_resistant_exit_when_deadline_expires_then_caller_is_bounded(
    monkeypatch,
) -> None:
    # Arrange
    _CancellationResistantExitSession.release = asyncio.Event()
    monkeypatch.setattr(
        remote_client_module,
        "streamable_http_client",
        lambda **_kwargs: _TaskBoundContext((object(), object(), None)),
    )
    monkeypatch.setattr(
        remote_client_module,
        "ClientSession",
        _CancellationResistantExitSession,
    )
    client = RemoteMcpClient("https://geofm.example", request_timeout_seconds=0.01)

    # Act & Assert
    try:
        with pytest.raises(RemoteMcpUnavailable, match="timed out"):
            await asyncio.wait_for(
                client.call_raw("geofm_list_models", {}),
                timeout=0.1,
            )
        assert client._active_task is not None
        with pytest.raises(RemoteMcpUnavailable, match="lifecycle is already in progress"):
            await client.call_raw("geofm_list_models", {})
    finally:
        _CancellationResistantExitSession.release.set()
        if client._active_task is not None:
            await asyncio.gather(client._active_task, return_exceptions=True)
    assert client._active_task is None


@pytest.mark.asyncio
async def test_given_concurrent_calls_when_first_lifecycle_is_active_then_second_is_rejected(
    monkeypatch,
) -> None:
    # Arrange
    release = asyncio.Event()

    class BlockingCallSession(_FakeSession):
        async def call_tool(self, _tool, _arguments):
            await release.wait()
            return await super().call_tool(_tool, _arguments)

    monkeypatch.setattr(
        remote_client_module,
        "streamable_http_client",
        lambda **_kwargs: _TaskBoundContext((object(), object(), None)),
    )
    monkeypatch.setattr(remote_client_module, "ClientSession", BlockingCallSession)
    client = RemoteMcpClient("https://geofm.example", request_timeout_seconds=1)
    first_call = asyncio.create_task(client.call_raw("geofm_list_models", {}))
    await asyncio.sleep(0)

    # Act & Assert
    try:
        with pytest.raises(RemoteMcpUnavailable, match="lifecycle is already in progress"):
            await client.call_raw("geofm_list_models", {})
    finally:
        release.set()
    assert await first_call == {"payload": {"models": []}}


@pytest.mark.asyncio
async def test_given_api_key_when_opening_session_then_http_client_carries_header(
    monkeypatch,
) -> None:
    # Arrange
    captured_header = None
    follows_redirects = None

    def transport(**kwargs):
        nonlocal captured_header, follows_redirects
        captured_header = kwargs["http_client"].headers.get("X-API-Key")
        follows_redirects = kwargs["http_client"].follow_redirects
        return _TaskBoundContext((object(), object(), None))

    monkeypatch.setattr(remote_client_module, "streamable_http_client", transport)
    monkeypatch.setattr(remote_client_module, "ClientSession", _FakeSession)
    client = RemoteMcpClient(
        "https://web-search.example",
        api_key="shared-secret",
        request_timeout_seconds=1,
    )

    # Act
    await client.call_raw("geofm_list_models", {})

    # Assert
    assert captured_header == "shared-secret"
    assert follows_redirects is False