---
title: Resilience MCP Wrapper
description: Connect an authorized existing Resilience API to MCP clients with separate inbound and backend credentials.
ms.date: 2026-09-08
---

## Scope

This CPU-only FastMCP service wraps the Planetary Explorer Resilience API.
It does not create the backend, deploy models, populate Fabric tables, install
a Teams app or implement user-delegated OAuth. Backend source/provenance may
be live tenant data or explicitly synthetic seed data; inspect each response.

| Tool | Backend Route |
| --- | --- |
| `check_resilience_health` | `/api/resilience/health` |
| `list_facilities` | `/api/resilience/facilities` |
| `assess_resilience` | `/api/resilience/assess` |
| `get_resilience_snapshot` | `/api/resilience/snapshot` |

See the [deployment/resource guide](../../documentation/deployment.md) and
[Get Started playbook](../../documentation/get-started-playbook.md) for backend
requirements. A wrapper health response does not prove model/data readiness.

## Local Startup

From this directory, using Python 3.11 or newer:

```powershell
uv venv --python 3.11
uv pip install -e '.[dev]'
$env:MCP_HOST = '127.0.0.1'
$env:MCP_PORT = '8765'
$env:RESILIENCE_API_BASE_URL = 'http://localhost:8000'
$env:MCP_BEARER_TOKEN = '<strong-secret-from-your-secret-store>'
.\.venv\Scripts\python.exe server.py
```

Set `RESILIENCE_API_BASE_URL` explicitly to the actual local or HTTPS backend;
the server's default port 8080 differs from the main local-development port.
The server does not load `.env` automatically. On macOS/Linux use exported
environment variables and `.venv/bin/python`.

`/mcp` uses Streamable HTTP; `/healthz` is an unauthenticated liveness probe.
When `MCP_BEARER_TOKEN` is configured, every MCP request must carry its matching
Bearer header. Without it the service is open and must stay on loopback.

The convenience launcher accepts `-BackendUrl` but can create a public tunnel
and print generated credentials. It is not the default secure path. Review
its actions before using it; never send printed tokens to chat or logs.

## Two Authentication Boundaries

`MCP_BEARER_TOKEN` protects client-to-wrapper traffic. Separately,
`RESILIENCE_API_KEY` is forwarded as a Bearer token to the backend. A protected
Entra backend requires an authorized token with the correct audience/tenant;
an arbitrary static string is not an Entra credential. Tokens expire, and
this wrapper does not implement automatic OAuth acquisition or per-user token
exchange. Do not expose it publicly until that lifecycle and access model
meet your requirements.

Use `RESILIENCE_TUNNEL_SKIP=1` only when the backend is an approved dev tunnel.
It changes the tunnel interstitial header, not backend authentication.

## VS Code Client

For a running protected local wrapper, configure `.vscode/mcp.json` without
committing the token:

```json
{
  "inputs": [
    {
      "id": "resilience-mcp-token",
      "type": "promptString",
      "description": "Resilience MCP access token",
      "password": true
    }
  ],
  "servers": {
    "planetary-explorer-resilience": {
      "type": "http",
      "url": "http://localhost:8765/mcp",
      "headers": {
        "Authorization": "Bearer ${input:resilience-mcp-token}"
      }
    }
  }
}
```

Other clients must support Streamable HTTP and the configured authentication.
Do not select “None” when the server requires a token. Client availability,
tenant policy and government-cloud support require separate confirmation.

## Tunnels and Deployment

The local server speaks HTTP. A TLS-terminating dev tunnel must forward HTTP
to port 8765, not attempt HTTPS to the local Python process. Public exposure
requires explicit approval, a protected MCP endpoint and backend authorization;
anonymous tunnel access alone is not an application security model.

The Dockerfile is a packaging starting point. The root azd workflow does not
deploy this wrapper. Create or explicitly select its host, registry, API URL,
ingress and secrets separately, then test MCP initialization and a real
authorized tool call. Neither a proxy nor an API gateway creates missing data
or model dependencies.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Test both missing/incorrect client credentials and backend denial, expiry,
timeout and success. Validate returned source metadata. Never count an
HTTP 200 error payload or a synthetic seed result as a successful private-data
integration.