"""Execution helpers for Agent Service function tools.

The Agent Service SDK awaits async tools but calls synchronous tools directly
on the event loop. Terrain, mobility, climate, comparison, damage, and vision
tools perform STAC searches and raster reads, so running them inline stalls
every other request, including health probes, on the single API worker.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import inspect
import json
from typing import Any, Callable, Iterable, Iterator

_MAX_TEXT_RESULT_CHARS = 500

_recorded_results: contextvars.ContextVar[list[dict[str, Any]] | None] = (
    contextvars.ContextVar("agent_tool_results", default=None)
)


def offload_blocking_tools(
    functions: Iterable[Callable[..., Any]],
) -> set[Callable[..., Any]]:
    """Return async tool callables that run synchronous work in worker threads.

    The wrappers keep each tool's name, docstring, and signature so the SDK
    publishes identical function definitions to the model.
    """
    return {_as_async_tool(function) for function in functions}


@contextlib.contextmanager
def record_tool_results() -> Iterator[list[dict[str, Any]]]:
    """Collect ``{"tool", "result"}`` entries for tools run in this context."""
    results: list[dict[str, Any]] = []
    token = _recorded_results.set(results)
    try:
        yield results
    finally:
        _recorded_results.reset(token)


def merge_recorded_tool_results(
    run_step_calls: list[dict[str, Any]],
    recorded: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fill missing run-step outputs with results captured at execution time.

    Agent Service run steps can report a function name with a null output
    after automatic function calling. The locally executed result is the
    evidence the response was based on, so it replaces the missing value.
    """
    unused = list(recorded)
    merged: list[dict[str, Any]] = []
    for call in run_step_calls:
        entry = dict(call)
        match = next(
            (index for index, item in enumerate(unused) if item["tool"] == entry.get("tool")),
            None,
        )
        if match is not None:
            captured = unused.pop(match)
            if entry.get("result") is None:
                entry["result"] = captured["result"]
        merged.append(entry)
    merged.extend(dict(item) for item in unused)
    return merged


def _as_async_tool(function: Callable[..., Any]) -> Callable[..., Any]:
    if inspect.iscoroutinefunction(function):

        @functools.wraps(function)
        async def run_async(*args: Any, **kwargs: Any) -> Any:
            result = await function(*args, **kwargs)
            _record(function.__name__, result)
            return result

        return run_async

    @functools.wraps(function)
    async def run_in_thread(*args: Any, **kwargs: Any) -> Any:
        result = await asyncio.to_thread(function, *args, **kwargs)
        _record(function.__name__, result)
        return result

    return run_in_thread


def _record(name: str, result: Any) -> None:
    sink = _recorded_results.get()
    if sink is not None:
        sink.append({"tool": name, "result": _parse_result(result)})


def _parse_result(result: Any) -> Any:
    if not isinstance(result, str):
        return result
    try:
        return json.loads(result)
    except (TypeError, ValueError):
        return result[:_MAX_TEXT_RESULT_CHARS]
