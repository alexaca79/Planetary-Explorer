"""Run the canonical release-bound example matrix with authenticated chat history."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import json
import os
import re
from typing import Any, Callable
import uuid

import httpx

import verify_get_started_scenarios as canonical


class HistoryRecorder:
    """Wrap real scenario requests with owner-authenticated transcript round trips."""

    def __init__(self, client: Any, post: Callable, token: str, model: str) -> None:
        self.client = client
        self.original_post = post
        self.token = token
        self.model = model
        self.prefix = f"doc-history-{uuid.uuid4().hex[:10]}"
        self.sessions: dict[str, dict[str, Any]] = {}
        self.checks: list[dict[str, Any]] = []

    def post(self, base_url: str, path: str, payload: dict, *, headers: dict | None = None):
        """Use the canonical request assertions, preserving the latest map and query."""
        body = dict(payload)
        original_id = str(body.get("session_id") or uuid.uuid4().hex)
        vision = re.match(r"get-started-vision-(?:setup|raster)-(\d+)-", original_id)
        alias = f"vision-{vision[1]}" if vision else original_id
        session = self.sessions.setdefault(alias, {
            "id": f"{self.prefix}-{len(self.sessions):02d}", "revision": 0,
            "messages": [], "title": "Documentation verification",
        })
        if session["revision"]:
            restored = self.client.get(f"/api/chat-history/sessions/{session['id']}")
            restored.raise_for_status()
            session["messages"] = restored.json()["messages"]
            session["revision"] = restored.json()["revision"]
        if path == "/api/query":
            body.update(session_id=session["id"], conversation_history=session["messages"], memory_enabled=True)
            body.setdefault("model", self.model)
        status, result = self.original_post(base_url, path, body, headers={
            **(headers or {}), "Authorization": f"Bearer {self.token}",
        })
        question = str(body.get("query") or body.get("user_query") or body.get("message") or "")
        answer = canonical._response_text(result)
        transcript = [
            *session["messages"],
            {"role": "user", "content": question, "timestamp": datetime.now(UTC).isoformat()},
            {"role": "assistant", "content": answer, "timestamp": datetime.now(UTC).isoformat(),
             "toolsUsed": result.get("tools_used", []) if isinstance(result, dict) else []},
        ]
        saved = self.client.put(f"/api/chat-history/sessions/{session['id']}", json={
            "title": question[:96], "expectedRevision": session["revision"], "mutationId": uuid.uuid4().hex,
            "messages": transcript, "memoryEnabled": True, "context": {"stacMode": body.get("stac_mode", "public")},
        })
        saved.raise_for_status()
        document = saved.json()
        restored = self.client.get(f"/api/chat-history/sessions/{session['id']}")
        restored.raise_for_status()
        assert restored.json()["messages"] == document["messages"], "Saved transcript did not round-trip."
        session["revision"] = document["revision"]
        session["messages"] = document["messages"]
        self.checks.append({
            "sessionId": session["id"], "endpoint": path, "query": question,
            "queryStatus": status, "revision": document["revision"], "messageCount": document["messageCount"],
            "saveRestore": "passed", "memory": result.get("memory") if isinstance(result, dict) else None,
        })
        return status, result

    def cleanup(self) -> list[dict[str, Any]]:
        """Delete only fixtures created by this verifier, recording any cleanup failure."""
        results = []
        for session in self.sessions.values():
            response = self.client.delete(f"/api/chat-history/sessions/{session['id']}")
            results.append({"sessionId": session["id"], "status": response.status_code})
        return results


def main() -> int:
    """Run source and release checks before exercising every selected example."""
    parser = canonical.create_parser()
    parser.add_argument("--family", help="Optional exact family for a focused rerun.")
    arguments = parser.parse_args()
    if not arguments.allow_production or not arguments.base_url or not arguments.output:
        parser.error("--base-url, --allow-production, and --output are required.")
    if not arguments.run_setups and not arguments.run_analyses:
        parser.error("Select --run-setups or --run-analyses.")
    token = os.getenv("PLANETARY_EXPLORER_ACCESS_TOKEN")
    if not token:
        parser.error("An application-scoped PLANETARY_EXPLORER_ACCESS_TOKEN is required.")
    release = canonical._verify_release_metadata(arguments, arguments.base_url)
    if not release:
        parser.error("Complete release-binding arguments are required.")
    scenarios = canonical.load_scenarios()
    canonical.validate_inventory(scenarios)
    if arguments.family:
        scenarios = [scenario for scenario in scenarios if scenario.family == arguments.family]
        if not scenarios:
            parser.error("Unknown scenario family.")
    report: dict[str, Any] = {"release": release}
    with httpx.Client(base_url=arguments.base_url, headers={"Authorization": f"Bearer {token}"}, timeout=90, follow_redirects=False) as client:
        recorder = HistoryRecorder(client, canonical._post_json, token, arguments.model)
        canonical._post_json = recorder.post
        try:
            if arguments.run_setups:
                report = canonical.run_setup_matrix(scenarios, arguments.base_url, release_metadata=release, adversarial_context=arguments.adversarial_context)
            else:
                report = canonical.run_analysis_matrix(scenarios, arguments.base_url, attempts=1, retry_delay_seconds=0, pace_seconds=max(0, arguments.pace_seconds), model=arguments.model, release_metadata=release)
            report["release"] = canonical._reverify_release_metadata(arguments, arguments.base_url, release)
        except Exception as error:
            report["error"] = f"{type(error).__name__}: {str(error)[:1200]}"
        finally:
            canonical._post_json = recorder.original_post
            report["history"] = recorder.checks
            report["cleanup"] = recorder.cleanup()
    report["summary"] = dict(Counter(row["outcome"] for row in report.get("results", [])))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    failed = bool(report.get("error") or report["summary"].get("fail") or any(row["status"] not in {204, 404} for row in report["cleanup"]))
    print(json.dumps({"summary": report["summary"], "historyRoundTrips": len(report["history"]), "error": report.get("error"), "cleanupPassed": not any(row["status"] not in {204, 404} for row in report["cleanup"])}))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())