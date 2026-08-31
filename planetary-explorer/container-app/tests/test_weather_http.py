"""Weather provider transport tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from connectors.weather import _http


class _ResponseContext:
    def __init__(self, response: SimpleNamespace | None = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error

    async def __aenter__(self) -> SimpleNamespace:
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Session:
    def __init__(self, responses: list[_ResponseContext]) -> None:
        self._responses = responses

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def post(self, *_args: object, **_kwargs: object) -> _ResponseContext:
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_given_cold_start_timeout_when_post_retried_then_returns_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    response = SimpleNamespace(status=200, json=_async_value({"status": "ok"}))
    responses = [
        _ResponseContext(error=asyncio.TimeoutError()),
        _ResponseContext(response=response),
    ]
    monkeypatch.setattr(_http, "_DEFAULT_ATTEMPTS", 2)
    monkeypatch.setattr(_http, "_DEFAULT_RETRY_DELAY_S", 0.0)
    monkeypatch.setattr(
        _http.aiohttp,
        "ClientSession",
        lambda **_kwargs: _Session(responses),
    )

    # Act
    result = await _http._post_json_with_cold_start_retry(
        url="https://weather.internal/score",
        headers={},
        payload={"lat": 43.65},
    )

    # Assert
    assert result == {"status": "ok"}
    assert responses == []


@pytest.mark.asyncio
async def test_given_http_failure_when_post_called_then_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    response = SimpleNamespace(
        status=503,
        text=_async_value("provider unavailable"),
    )
    responses = [
        _ResponseContext(response=response),
        _ResponseContext(error=AssertionError("unexpected retry")),
    ]
    monkeypatch.setattr(_http, "_DEFAULT_ATTEMPTS", 2)
    monkeypatch.setattr(
        _http.aiohttp,
        "ClientSession",
        lambda **_kwargs: _Session(responses),
    )

    # Act & Assert
    with pytest.raises(RuntimeError, match="scoring endpoint returned 503"):
        await _http._post_json_with_cold_start_retry(
            url="https://weather.internal/score",
            headers={},
            payload={"lat": 43.65},
        )
    assert len(responses) == 1


def _async_value(value: object):
    async def get_value() -> object:
        return value

    return get_value