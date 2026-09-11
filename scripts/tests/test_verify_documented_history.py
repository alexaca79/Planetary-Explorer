"""Verify that history-wrapped scenarios retain auth, map context, and source checks."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import httpx


SCRIPT_DIRECTORY = Path(__file__).parents[1]
sys.path.insert(0, str(SCRIPT_DIRECTORY))
SPEC = importlib.util.spec_from_file_location("verify_documented_history", SCRIPT_DIRECTORY / "verify_documented_history.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_given_setup_and_analysis_when_recorded_then_restored_history_and_map_are_forwarded():
    documents = {}
    requests = []

    def storage(request):
        import json

        if request.method == "PUT":
            payload = json.loads(request.content)
            documents[request.url.path] = {**payload, "revision": payload["expectedRevision"] + 1, "messageCount": len(payload["messages"])}
        if request.method == "DELETE":
            documents.pop(request.url.path, None)
            return httpx.Response(204)
        return httpx.Response(200, json=documents[request.url.path])

    def post(base_url, path, payload, *, headers):
        requests.append((payload, headers))
        return 200, {"response": "Canonical result", "tools_used": ["sample_raster_value"]}

    with httpx.Client(base_url="https://fixture.example", transport=httpx.MockTransport(storage)) as client:
        recorder = MODULE.HistoryRecorder(client, post, "fixture-token", "gpt-4o")
        recorder.post("https://fixture.example", "/api/query", {"query": "Setup", "session_id": "get-started-vision-setup-01-100"})
        recorder.post("https://fixture.example", "/api/query", {"query": "Analyze", "session_id": "get-started-vision-raster-01-200", "pin": {"lat": 50, "lng": -89}})
        cleanup = recorder.cleanup()

    assert requests[0][0]["session_id"] == requests[1][0]["session_id"]
    assert len(requests[1][0]["conversation_history"]) == 2
    assert requests[1][0]["pin"] == {"lat": 50, "lng": -89}
    assert requests[1][1] == {"Authorization": "Bearer fixture-token"}
    assert len(recorder.checks) == 2
    assert cleanup[0]["status"] == 204