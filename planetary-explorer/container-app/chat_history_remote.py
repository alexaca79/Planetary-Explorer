"""Authenticated forwarding to a private-network history data service."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from chat_history_api import get_request_owner


router = APIRouter(prefix="/api/chat-history", tags=["chat-history"])


def remote_history_url() -> str:
    """Resolve only an operator-configured HTTPS service origin."""
    value = os.getenv("CHAT_HISTORY_REMOTE_URL", "").strip().rstrip("/")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username
        or parsed.password or parsed.query or parsed.fragment or parsed.path
    ):
        raise ValueError("CHAT_HISTORY_REMOTE_URL must be an HTTPS origin without credentials or a path.")
    return value


def _bearer_header(authorization: str | None) -> dict[str, str]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in to use chat history.")
    return {"Authorization": authorization}


async def recall_remote_history(body: dict[str, Any], authorization: str | None) -> dict[str, Any]:
    """Let the data service validate the user again and retrieve canonical memory."""
    async with httpx.AsyncClient(timeout=6.0, follow_redirects=False) as client:
        response = await client.post(
            f"{remote_history_url()}/api/chat-memory/recall",
            headers=_bearer_header(authorization),
            json={key: body[key] for key in ("query", "user_query", "session_id", "conversation_history", "memory_enabled") if key in body},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("context"), str):
            raise ValueError("History service returned an invalid memory context.")
        if len(payload["context"]) > 30000:
            raise ValueError("History service exceeded the memory context budget.")
        return payload


@router.api_route("/{path:path}", methods=["GET", "PUT", "POST", "DELETE"])
async def forward_history(
    path: str, request: Request, owner_id: str = Depends(get_request_owner),
) -> Response:
    """Forward bounded history operations without trusting client identity headers."""
    del owner_id
    if path != "sessions" and not path.startswith("sessions/"):
        raise HTTPException(status_code=404, detail="History route not found.")
    headers = _bearer_header(request.headers.get("Authorization"))
    if request.headers.get("Content-Type"):
        headers["Content-Type"] = request.headers["Content-Type"]
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
            upstream = await client.request(
                request.method,
                f"{remote_history_url()}/api/chat-history/{quote(path, safe='/')}",
                headers=headers,
                params=request.query_params,
                content=await request.body(),
            )
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Chat history service is temporarily unavailable.") from exc
    response_headers = {
        name: upstream.headers[name]
        for name in ("Content-Type", "Content-Disposition", "X-Content-Type-Options")
        if name in upstream.headers
    }
    response_headers["Cache-Control"] = "private, no-store"
    return Response(content=upstream.content, status_code=upstream.status_code, headers=response_headers)