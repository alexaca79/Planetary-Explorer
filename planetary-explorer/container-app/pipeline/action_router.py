"""
Layer 1 — Action Router.

One LLM call per chat turn classifies the user's request into one of four
actions:

  * NAVIGATE          — fly the map to a location, no data load, no analysis
  * LOAD              — STAC search + render imagery, no analysis
  * ANALYZE           — use already-loaded data + map state to answer
  * LOAD_AND_ANALYZE  — load new imagery, then analyze it

This is intentionally narrower than the legacy 5-intent classifier. WHICH
analyzer to invoke is decided by the AnalysisRouter (Layer 2), not here.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from ._aoai import fast_deployment, get_aoai_client
from .contracts import ActionDecision
from .prompts import ACTION_ROUTER_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_EXPLICIT_WEB_REQUEST = re.compile(
    r"\b(?:search|browse)\s+(?:the\s+)?(?:public\s+)?web\b"
    r"|\b(?:look\s*up|lookup)\b.{0,200}\b(?:on\s+)?the\s+(?:public\s+)?web\b"
    r"|\bweb\s+search\b",
    re.IGNORECASE,
)
_IMAGERY_DISPLAY_REQUEST = re.compile(
    r"\b(?:show|load|display)\b.{0,240}\b(?:imagery|images?)\b",
    re.IGNORECASE | re.DOTALL,
)
_CURRENT_POINT_REFERENCE = re.compile(
    r"\b(?:at|around|over|for|of)\s+"
    r"(?:(?:the|this|that|my|current|dropped|selected|pinned)\s+)*(?:pin|point|location)\b"
    r"|\bhere\b",
    re.IGNORECASE,
)
_EXPLICIT_AREA_REFERENCE = re.compile(
    r"\b(?:whole|entire|visible|current)\s+(?:(?:visible|map)\s+)?"
    r"(?:map|area|extent|region|viewport)\b"
    r"|\b(?:over|within|across|for)\s+(?:the\s+)?(?:viewport|bbox|bounding box|map extent)\b"
    r"|\bwithin\b.{0,40}\b(?:km|kilometers|kilometres|meters|metres|miles|radius)\b",
    re.IGNORECASE,
)
_ANALYSIS_REQUEST = re.compile(
    r"\b(?:analy[sz]e|analysis|compare|comparison|calculate|compute|estimate|measure|"
    r"assess|explain|report|summari[sz]e|nbr|dnbr|ndvi|how|what|why)\b",
    re.IGNORECASE,
)


def is_explicit_web_request(query: str) -> bool:
    """Return whether the user explicitly requested public-web retrieval."""
    return bool(_EXPLICIT_WEB_REQUEST.search(query))


def is_pin_imagery_load(query: str) -> bool:
    """Identify an explicit display-only request referring to the current pin."""
    return bool(
        _IMAGERY_DISPLAY_REQUEST.search(query)
        and _CURRENT_POINT_REFERENCE.search(query)
        and not _ANALYSIS_REQUEST.search(query)
    )


def is_point_scoped_query(query: str) -> bool:
    """Distinguish a pin-local request from an explicitly requested area."""
    return bool(
        _CURRENT_POINT_REFERENCE.search(query)
        and not _EXPLICIT_AREA_REFERENCE.search(query)
    )


def resolve_pin_imagery_followup(query: str, history: list[dict[str, Any]]) -> str:
    """Resolve a nearest-date follow-up only against the last user imagery load."""
    if (
        not re.search(r"\b(?:nearest|closest|closes)\b", query, re.IGNORECASE)
        or not re.search(r"\b(?:date|day|acquisition|scene|image|imagery)\b", query, re.IGNORECASE)
        or _ANALYSIS_REQUEST.search(query)
        or is_explicit_web_request(query)
    ):
        return query
    for message in reversed(history):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        previous_query = message.get("content")
        if not isinstance(previous_query, str) or previous_query.strip() == query.strip():
            continue
        if not is_pin_imagery_load(previous_query):
            return query
        return (
            f"{previous_query} Use the nearest available acquisition to the requested "
            f"date at the current pin. {query}"
        )
    return query


_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {
            "type": "string",
            "enum": ["NAVIGATE", "LOAD", "ANALYZE", "LOAD_AND_ANALYZE"],
        },
        "location": {"type": ["string", "null"]},
        "use_current_location": {"type": "boolean"},
        "stac_query": {"type": ["string", "null"]},
        "analysis_question": {"type": ["string", "null"]},
        "reasoning": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": [
        "action",
        "location",
        "use_current_location",
        "stac_query",
        "analysis_question",
        "reasoning",
        "confidence",
    ],
}


class ActionRouter:
    """Single-call structured-output classifier."""

    def __init__(self, deployment: str | None = None) -> None:
        self._deployment = deployment or fast_deployment()

    async def route(
        self,
        query: str,
        loaded_collections: list[str] | None = None,
        has_pin: bool = False,
        has_screenshot: bool = False,
        memory_context: str = "",
    ) -> ActionDecision:
        if is_explicit_web_request(query):
            return ActionDecision(
                action="ANALYZE",
                analysis_question=query,
                reasoning="explicit_web_search",
                confidence=1.0,
            )

        if has_pin and is_pin_imagery_load(query):
            return ActionDecision(
                action="LOAD",
                use_current_location=True,
                stac_query=query,
                reasoning="explicit_pin_imagery_load",
                confidence=1.0,
            )

        ctx_lines = []
        if loaded_collections:
            ctx_lines.append(f"Currently loaded collections: {', '.join(loaded_collections)}")
        if has_pin:
            ctx_lines.append("A pin is dropped on the map.")
        if has_screenshot:
            ctx_lines.append("A screenshot of the map is available.")
        if memory_context:
            ctx_lines.append(memory_context)
        context_block = "\n".join(ctx_lines) or "(empty map state)"

        client = get_aoai_client()
        started = time.time()
        try:
            resp = await client.chat.completions.create(
                model=self._deployment,
                messages=[
                    {"role": "system", "content": ACTION_ROUTER_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"MAP STATE:\n{context_block}\n\nUSER QUERY:\n{query}",
                    },
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "ActionDecision",
                        "schema": _RESPONSE_SCHEMA,
                        "strict": True,
                    },
                },
                temperature=0.0,
            )
            payload = json.loads(resp.choices[0].message.content or "{}")
            decision = ActionDecision.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 - fail-open to ANALYZE
            logger.warning("[ACTION_ROUTER] Falling back to ANALYZE on error: %s", exc)
            decision = ActionDecision(
                action="ANALYZE",
                analysis_question=query,
                reasoning=f"router_fallback:{type(exc).__name__}",
                confidence=0.0,
            )

        elapsed = int((time.time() - started) * 1000)
        logger.info(
            "[ACTION_ROUTER] %s confidence=%.2f elapsed_ms=%d",
            decision.action,
            decision.confidence,
            elapsed,
        )
        return decision
