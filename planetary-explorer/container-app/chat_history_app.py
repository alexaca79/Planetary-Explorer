"""Authenticated history service for deployments using private data endpoints."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os

from fastapi import Depends, FastAPI, HTTPException, Request

from auth_middleware import EntraAuthMiddleware
from chat_history_api import get_request_owner, router
from chat_memory import prepare_chat_memory
from security_middleware import RequestBodyLimitMiddleware, SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Fail closed for shared history and initialize only its dedicated index."""
    if os.getenv("DISABLE_AUTH", "false").lower() in {"true", "1", "yes"}:
        raise RuntimeError("The history data service requires Entra authentication.")
    if os.getenv("CHAT_HISTORY_ALLOW_ANONYMOUS", "false").lower() in {"true", "1", "yes", "on"}:
        raise RuntimeError("Anonymous history is forbidden on the data service.")
    if os.getenv("CHAT_MEMORY_AUTO_SETUP", "false").lower() == "true":
        from setup_chat_memory import configure_memory_index_from_env

        await asyncio.to_thread(configure_memory_index_from_env)
    yield


app = FastAPI(title="Planetary Explorer History", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(EntraAuthMiddleware)
app.add_middleware(RequestBodyLimitMiddleware, max_body_bytes=33554432)
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Expose process readiness without exposing chat data or credentials."""
    return {"status": "healthy", "service": "chat-history"}


@app.post("/api/chat-memory/recall")
async def recall(request: Request, owner_id: str = Depends(get_request_owner)) -> dict:
    """Assemble bounded memory for this validated user, not a supplied owner ID."""
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Memory request must be an object.")
    await prepare_chat_memory(body, owner_id, body.get("session_id"))
    return {
        "context": body["_chat_memory_context"],
        "memory": body["_chat_memory"],
        "history": body["conversation_history"],
    }