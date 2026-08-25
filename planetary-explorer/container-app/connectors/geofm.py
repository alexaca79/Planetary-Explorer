"""GeoFM MCP connector for Planetary Explorer."""

from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

from mcp_runtime.remote_client import RemoteMcpClient

logger = logging.getLogger(__name__)
_health_probe_task: asyncio.Task[dict[str, Any]] | None = None


def is_enabled() -> bool:
    """Return whether the GeoFM capability is configured and enabled."""
    enabled = os.getenv("GEOFM_ENABLED", "false").casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return enabled and bool((os.getenv("GEOFM_MCP_URL") or "").strip())


@lru_cache(maxsize=1)
def get_client() -> RemoteMcpClient:
    """Return the process-wide GeoFM MCP client."""
    return RemoteMcpClient(
        os.getenv("GEOFM_MCP_URL", ""),
        api_key=os.getenv("GEOFM_MCP_API_KEY") or None,
        request_timeout_seconds=float(os.getenv("GEOFM_MCP_TIMEOUT_SECONDS", "30")),
    )


@lru_cache(maxsize=1)
def get_health_client() -> RemoteMcpClient:
    """Return the process-wide GeoFM health-probe client."""
    timeout = min(float(os.getenv("GEOFM_MCP_TIMEOUT_SECONDS", "30")), 5.0)
    return RemoteMcpClient(
        os.getenv("GEOFM_MCP_URL", ""),
        api_key=os.getenv("GEOFM_MCP_API_KEY") or None,
        request_timeout_seconds=timeout,
    )


async def get_health_snapshot() -> dict[str, Any]:
    """Probe the configured GeoFM MCP without reusing the analysis session."""
    endpoint = (os.getenv("GEOFM_MCP_URL") or "").strip()
    base = {
        "enabled": is_enabled(),
        "connected": False,
        "endpoint_host": urlsplit(endpoint).hostname or "",
        "tool_count": 0,
        "tools": [],
        "models": [],
    }
    if not base["enabled"]:
        return {**base, "status": "disabled"}

    global _health_probe_task
    if _health_probe_task is None or _health_probe_task.done():
        _health_probe_task = asyncio.create_task(_probe_health_snapshot(base))
    return await asyncio.shield(_health_probe_task)


async def _probe_health_snapshot(base: dict[str, Any]) -> dict[str, Any]:
    """Run one shared GeoFM health probe for concurrent callers."""
    client = get_health_client()
    try:
        result = await client.call_raw("geofm_list_models", {})
        payload = result.get("payload", {}) if isinstance(result, dict) else {}
        models = payload.get("models", [])
        normalized_models = [
            {
                "profile": model.get("profile", ""),
                "model_id": model.get("model_id", ""),
                "model_revision": model.get("model_revision", ""),
                "approval_state": model.get("approval_state", ""),
                "supported_collections": model.get("supported_collections", []),
                "geographic_scope": model.get("geographic_scope", ""),
                "license": model.get("license", ""),
            }
            for model in models
            if isinstance(model, dict)
        ]
        tools = list(client.available_tools)
        return {
            **base,
            "status": "connected",
            "connected": True,
            "tool_count": len(tools),
            "tools": tools,
            "models": normalized_models,
        }
    except Exception as exc:
        logger.warning("GeoFM health probe failed: %s", exc)
        return {**base, "status": "degraded"}