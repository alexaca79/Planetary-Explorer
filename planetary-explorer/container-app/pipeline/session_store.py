"""
Session context store.

Plain in-process dict wrapper that holds per-session routing/render state
(last_bbox, last_location, last_collections, last_stac_items, query_count,
has_rendered_map, has_screenshot, pending_clarification, ...).

This module is the single source of truth so both the router compatibility
surface and pipeline executors can read and write the same state.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def scope_session_id(owner_id: str, client_session_id: str | None) -> str:
    """Return a stable internal key isolated by authenticated owner."""
    conversation_id = client_session_id or "anonymous"
    digest = hashlib.sha256(
        f"{owner_id}\0{conversation_id}".encode("utf-8")
    ).hexdigest()
    return f"session-{digest}"


class SessionContextStore:
    """Thread-unsafe per-session dict store. Single-process FastAPI is fine."""

    def __init__(self) -> None:
        self._contexts: Dict[str, Dict[str, Any]] = {}
        self._last_seen: Dict[str, datetime] = {}

    # The raw dict is exposed so legacy code that reads
    # `router_agent.tools.session_contexts.get(sid, {})` keeps working
    # without modification.
    @property
    def raw(self) -> Dict[str, Dict[str, Any]]:
        return self._contexts

    def get(self, session_id: str) -> Dict[str, Any]:
        return self._contexts.get(session_id, {})

    def update(self, session_id: str, partial: Dict[str, Any]) -> Dict[str, Any]:
        existing = self._contexts.get(session_id, {})
        existing.update(partial)
        self._contexts[session_id] = existing
        self._last_seen[session_id] = datetime.utcnow()
        return existing

    def delete(self, session_id: str) -> None:
        self._contexts.pop(session_id, None)
        self._last_seen.pop(session_id, None)

    def cleanup_older_than(self, max_age_minutes: int = 60) -> int:
        now = datetime.utcnow()
        expired = [
            sid for sid, ts in self._last_seen.items()
            if (now - ts).total_seconds() > max_age_minutes * 60
        ]
        for sid in expired:
            self.delete(sid)
        if expired:
            logger.info("[SessionStore] cleaned %d expired sessions", len(expired))
        return len(expired)


_store: Optional[SessionContextStore] = None


def get_session_store() -> SessionContextStore:
    global _store
    if _store is None:
        _store = SessionContextStore()
    return _store
