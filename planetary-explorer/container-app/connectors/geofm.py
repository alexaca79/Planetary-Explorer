"""GeoFM MCP connector for Planetary Explorer."""

from __future__ import annotations

import os
from functools import lru_cache

from mcp_runtime.remote_client import RemoteMcpClient


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