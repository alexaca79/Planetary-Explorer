"""Verify authenticated deployed history and model recall using temporary owned fixtures."""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import uuid
from zipfile import ZipFile

import httpx


def main() -> int:
    """Exercise real owned history and recall without spoofing authentication."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if not arguments.allow_production or not arguments.base_url.startswith("https://"):
        parser.error("An HTTPS origin and --allow-production are required.")
    token = os.getenv("PLANETARY_EXPLORER_ACCESS_TOKEN")
    if not token:
        parser.error("PLANETARY_EXPLORER_ACCESS_TOKEN must contain an app-scoped signed-in user token.")
    identifier = uuid.uuid4().hex[:12]
    source_id = f"memory-verify-source-{identifier}"
    source_title = f"Memory verification {identifier}"
    fixture_ids: list[str] = []
    report: dict = {"baseUrl": arguments.base_url, "fixture": identifier, "checks": []}
    client = httpx.Client(base_url=arguments.base_url.rstrip("/"), headers={"Authorization": f"Bearer {token}"}, timeout=180, follow_redirects=False)

    def save(session_id: str, messages: list[dict], revision: int = 0, enabled: bool = True) -> dict:
        if session_id not in fixture_ids:
            fixture_ids.append(session_id)
        response = client.put(f"/api/chat-history/sessions/{session_id}", json={
            "title": source_title, "expectedRevision": revision, "mutationId": uuid.uuid4().hex,
            "memoryEnabled": enabled, "messages": messages, "context": {},
        })
        response.raise_for_status()
        return response.json()

    def ask(session_id: str, question: str, history: list[dict] | None = None) -> dict:
        response = client.post("/api/query", json={
            "query": question, "session_id": session_id, "model": arguments.model,
            "memory_enabled": True, "conversation_history": history or [],
        })
        response.raise_for_status()
        return response.json()

    try:
        anonymous = httpx.get(f"{arguments.base_url.rstrip('/')}/api/chat-history/sessions", timeout=30)
        assert anonymous.status_code == 401, "Anonymous history was not rejected."
        report["checks"].append("anonymous-rejected")
        messages = [
            {"role": "user", "content": f"For synthetic project {identifier}, our agreed Thunder Bay baseline is June 1, 2026. This is a test plan date, not a measured observation."},
            *[{"role": "assistant", "content": f"Unrelated discussion number {index}."} for index in range(12)],
        ]
        document = save(source_id, messages)
        loaded = client.get(f"/api/chat-history/sessions/{source_id}")
        loaded.raise_for_status()
        assert loaded.json()["messages"][0]["content"] == messages[0]["content"]
        report["checks"].append("durable-save-and-read")

        question = f"What exact baseline date did we agree for synthetic project {identifier} at Thunder Bay? Recall our plan, do not search imagery or calculate anything."
        same = ask(source_id, question, messages[-3:])
        same_text = str(same.get("answer") or same.get("response") or "")
        assert "June 1" in same_text or "2026-06-01" in same_text, same_text[:500]
        assert same.get("memory", {}).get("earlierTurns", 0) > 0, "Older same-chat context was not used."
        report["sameChat"] = {"answer": same_text, "memory": same.get("memory")}
        report["checks"].append("same-chat-model-recall")

        cross = ask(f"memory-verify-fresh-{identifier}", question)
        cross_text = str(cross.get("answer") or cross.get("response") or "")
        assert "June 1" in cross_text or "2026-06-01" in cross_text, cross_text[:500]
        assert cross.get("memory", {}).get("provider") == "azure-search", "Cross-chat recall did not use Azure AI Search."
        assert any(source["sessionId"] == source_id for source in cross["memory"]["sources"])
        report["crossChat"] = {"answer": cross_text, "memory": cross.get("memory")}
        report["checks"].append("search-backed-cross-chat-model-recall")

        content = b"latitude,longitude\n50.268,-89.8572\n"
        upload = client.post(f"/api/chat-history/sessions/{source_id}/files", files={"file": ("memory-probe.csv", content, "text/csv")})
        upload.raise_for_status()
        attachment_id = upload.json()["id"]
        download = client.get(f"/api/chat-history/sessions/{source_id}/files/{attachment_id}")
        download.raise_for_status()
        assert download.content == content
        exported = client.get(f"/api/chat-history/sessions/{source_id}/export")
        exported.raise_for_status()
        with ZipFile(io.BytesIO(exported.content)) as archive:
            assert archive.read("files/memory-probe.csv") == content
            assert "ownerId" not in json.loads(archive.read("session.json"))
        report["checks"].append("attachment-roundtrip-and-export")

        save(source_id, messages, document["revision"], enabled=False)
        excluded = ask(f"memory-verify-excluded-{identifier}", question)
        assert not any(source["sessionId"] == source_id for source in excluded.get("memory", {}).get("sources", []))
        report["checks"].append("excluded-session-not-recalled")
        deleted = client.delete(f"/api/chat-history/sessions/{source_id}")
        deleted.raise_for_status()
        assert client.get(f"/api/chat-history/sessions/{source_id}").status_code == 404
        report["checks"].append("session-and-file-deletion")
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {str(error)[:1000]}"
    finally:
        cleanup = []
        for session_id in fixture_ids:
            try:
                result = client.delete(f"/api/chat-history/sessions/{session_id}")
                cleanup.append({"sessionId": session_id, "status": result.status_code})
            except httpx.HTTPError:
                cleanup.append({"sessionId": session_id, "status": "cleanup-failed"})
        report["cleanup"] = cleanup
        if any(item["status"] not in {204, 404} for item in cleanup):
            report["status"] = "failed"
        client.close()
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report.get(key) for key in ("status", "checks", "error", "cleanup")}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())