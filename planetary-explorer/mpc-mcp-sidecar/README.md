---
title: MPC Pro MCP Sidecar
description: Deploy or reference the CPU catalog bridge and verify private GeoCatalog authorization with the MCP SDK.
---

## Scope

Internal-only Container App that runs Microsoft's `geocatalog-mcp-server`
(v1.0.9, MIT) behind a streamable-HTTP transport so the Planetary Explorer
backend can call its tools as a network MCP client.

This service uses CPU only and is optional for the public-data baseline.
It does not create a private GeoCatalog, ingest imagery or grant catalog
access. [Deployment prerequisites](../../documentation/deployment.md#resources-and-responsibilities)
must be completed for the selected catalog and backend identity.

## Architecture (Option A: vendor + bridge)

The upstream `geocatalog-mcp-server` is distributed only as a pre-built
bundle inside the VS Code extension `ms-planetarycomputer.mpc-pro-mcp-tools`
— there is no buildable source in the GitHub repo, and the bundled
binary speaks **stdio MCP only**. To run it as a network service we:

1. **Vendor** the bundled `server_main.js` (MIT) into [`vendor/`](./vendor/PROVENANCE.md).
2. Run a thin **`bridge.mjs`** in the same container that
   - spawns `node vendor/server_main.js` as a long-lived stdio child,
   - connects an MCP `Client` to it via `StdioClientTransport`, and
   - exposes a streamable-HTTP MCP `Server` on `:8080` that proxies
     `tools/*`, `resources/*`, and `prompts/*` to the child.
3. Use **`az login --identity`** at container startup so the upstream's
   `AzureCliCredential` finds a token cache backed by the workload's
   managed identity. We do **not** patch upstream code.

```
┌───────────────────── Container App: mpc-mcp ─────────────────────┐
│                                                                  │
│  docker-entrypoint.sh                                            │
│    └─ az login --identity        # populates AzureCliCredential  │
│       └─ exec node bridge.mjs                                    │
│                                                                  │
│  bridge.mjs            spawn (stdio)        vendor/server_main.js│
│   ├─ MCP Client  ─────────────────────►  upstream binary (MIT)   │
│   ├─ MCP Server                                                  │
│   │   on streamable-HTTP                                         │
│   │   :8080 /mcp                                                 │
│   └─ /healthz                                                    │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Files

| Path | Purpose |
|---|---|
| `vendor/server_main.js` | MIT, vendored from VSIX v1.0.9. **Do not edit.** |
| `vendor/PROVENANCE.md` | Source, license, upgrade procedure. |
| `vendor/LICENSE-UPSTREAM` | MIT attribution. |
| `vendor/package.upstream.json` | Used as `package.json` in image (dep tree). |
| `vendor/package-lock.upstream.json` | Used as `package-lock.json` in image. |
| `bridge.mjs` | stdio ↔ streamable-HTTP proxy. |
| `healthcheck.mjs` | Used by Docker `HEALTHCHECK` and Container Apps probes. |
| `docker-entrypoint.sh` | `az login --identity` then `exec node bridge.mjs`. |
| `Dockerfile` | Two-stage `node:20-bookworm-slim` build. |

## Why a separate Container App, not a multi-container sidecar

Container Apps does support multi-container apps (sharing localhost), but
that ties the MCP server's lifecycle and revision to the backend's. A
separate internal Container App lets us:

- bump the MCP image independently (Microsoft's release cadence is its own),
- restart it without restarting the backend,
- run a smaller replica pool (catalog calls cache well),
- keep the backend image lean (no Node + az CLI in Python image).

Internal-only ingress means it is reachable only from inside the
Container Apps environment, never from the public internet.

## What it exposes

The full MPC Pro MCP tool surface (`tools/list` against `/mcp` returns
~28 tools — see [`vendor/PROVENANCE.md`](./vendor/PROVENANCE.md) for the
exact upstream version). Highlights used by `LoadAgent`:

| Tool | Used for |
| --- | --- |
| `list_mpc_stac_collections` | inventory the public MPC catalog |
| `list_personal_stac_collections` | inventory the Pro GeoCatalog |
| `search_mpc_items` | run STAC search against MPC Public |
| `search_personal_collection_items` | run STAC search against Pro |
| `get_mpc_collection_json` / `get_personal_collection_details` | resolve render config from the STAC `renders` extension |
| `check_mpc_collection_exists` / `check_personal_collection_exists` | literal-id passthrough validation |

## Auth

The vendored binary calls
`new AzureCliCredential().getToken("https://geocatalog.spatio.azure.com/.default")`
i.e. it acquires a bearer for the GeoCatalog **data plane**, not ARM. We
satisfy `AzureCliCredential` by running `az login --identity` in
`docker-entrypoint.sh` so the system-assigned MI populates the CLI's
token cache.

Verified against `ms-planetarycomputer.mpc-pro-mcp-tools` v1.0.9:

```
await new AzureCliCredential().getToken(`${e}/.default`)   // e = https://geocatalog.spatio.azure.com
headers["Authorization"] = `Bearer ${token}`
headers["User-Agent"]    = "MPC-MCP-1.0.9"
params["api-version"]    = "2025-04-30-preview"
```

Access to a specific GeoCatalog instance is **granted inside that
instance** (data-plane RBAC via the MPC Pro portal or GeoCatalog Admin
API), *not* through ARM RBAC. The Bicep module therefore only does the
ARM-level grants the Container App actually needs (`AcrPull` on the
registry).

### User-assigned MI

If you front the sidecar with a user-assigned managed identity instead
of system-assigned, set the env var `MPC_MCP_IDENTITY_CLIENT_ID` to the
UA-MI client id. `docker-entrypoint.sh` will pass `--username <client_id>`
to `az login --identity`.

### Post-deploy: add the sidecar MI as a GeoCatalog member

After `mpc-mcp.bicep` deploys, grab `outputs.principalId` and add it
inside the GeoCatalog instance:

1. Open the GeoCatalog instance in the MPC Pro portal.
2. **Settings → Access control → Add member**.
3. Paste the principal id (object id of the sidecar's MI).
4. Role:
   - **Reader** — sufficient for the read-only catalog routing path
     (Phase 2).
   - **Contributor** — only if you also want the agent-driven ingest
     tools to be callable.

If the GeoCatalog backing storage is *not* public and the agent will
read asset bytes directly (rare; SAS-signed URLs are the usual path),
additionally grant the same MI `Storage Blob Data Reader` on the storage
account via ARM RBAC.

## Build

This Dockerfile **does not clone from upstream** — the upstream GitHub
path has no source (see `vendor/PROVENANCE.md`). The vendored bundle in
`vendor/` is the source of truth.

```powershell
# Local Docker (if available):
docker build -t planetary-explorer-mpc-mcp:v1.0.9 .

# Azure Container Registry build (no Docker daemon needed):
az acr build `
  --registry <acr-name> `
  --image planetary-explorer-mpc-mcp:v1.0.9 `
  --file Dockerfile `
  .
```

Image size: ~400 MB (node:20-slim ~150 MB + az CLI ~250 MB).

## Deploy

The Bicep module is [`planetary-explorer/infra/app/mpc-mcp.bicep`](../infra/app/mpc-mcp.bicep).
It is gated by `param deployMpcMcp` (default `false`) in
[`main.bicep`](../infra/main.bicep). Set it to `true` to wire the
sidecar in alongside the backend.

The backend container app needs one new env var (already plumbed by
`web.bicep`):

| Env var | Value |
| --- | --- |
| `MPC_MCP_URL` | `https://<sidecar-fqdn>` (internal, env-scoped) |
| `USE_MPC_MCP` | `false` initially — flip to `true` after smoke-test passes |

## Smoke test (after deploy + GeoCatalog grant)

Use the [SDK smoke test](../container-app/tools/mpc_mcp_smoke.py) from the
backend working directory with its dependencies installed and network access
to the internal endpoint:

```bash
export MPC_MCP_URL='https://<actual-sidecar-fqdn>'
export MPC_PRO_STAC_URL='https://<authorized-geocatalog>/stac'
PYTHONPATH=. python tools/mpc_mcp_smoke.py
```

The SDK manages initialization and session headers, then calls the private
collection inventory tool. A successful Public PC query does not validate
private GeoCatalog permissions. Inspect the returned collection IDs and run
an authorized item/asset check before enabling private workflows. An empty
inventory can prove the transport works without proving your required data
exists. Do not parse an SSE stream as an ordinary JSON response.
