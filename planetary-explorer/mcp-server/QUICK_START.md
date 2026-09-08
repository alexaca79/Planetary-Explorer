---
title: Local MCP Bridge Experiment
description: Run the legacy mock HTTP bridge on CPU and loopback without deploying Azure resources.
---

## Local CPU-Only Run

Read the [status and limitations](README.md) first. From this directory:

```powershell
uv venv --python 3.11
uv pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn mcp_bridge:app --host 127.0.0.1 --port 8085
```

On macOS/Linux use `.venv/bin/python` in the last command. Open
<http://127.0.0.1:8085/docs> to inspect the mock HTTP API. This does not
provision Azure, initialize a production MCP session, or run real agent tools.

The legacy scripts do not load `.env` automatically. The stdio server is not
a drop-in replacement: its MCP dependency and obsolete import path need
implementation work. Do not expose this template through a public tunnel or
deploy a hello-world image and call it ready.

Use the [real application CPU path](../../documentation/deployment.md#non-gpu-baseline)
or a service-specific MCP wrapper when you need actual backend behavior.