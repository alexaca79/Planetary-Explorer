---
title: Azure Web Search MCP
description: Deploy and operate the Planetary Explorer MCP service backed by Microsoft Foundry Web Search
ms.date: 2026-08-26
ms.topic: how-to
---

## Overview

This service exposes two read-only Streamable HTTP MCP tools:

* `web_search` calls the GA Microsoft Foundry `web_search` tool and returns a
  grounded answer with URL citations
* `get_current_datetime` returns the current date and time from the MCP host
  system clock in an IANA timezone

The service runs as an internal Azure Container App in the same environment as
the Planetary Explorer API. Its managed identity authenticates to the existing
Microsoft Foundry project. It does not create or store a Bing API key.

## Deploy

Enable the optional service in the selected Azure Developer CLI environment:

```powershell
azd env set DEPLOY_WEB_SEARCH_MCP true
azd env set WEB_SEARCH_MCP_API_KEY <random-value-with-at-least-32-characters>
azd up
```

The root and nested `azure.yaml` manifests both package
`planetary-explorer/web-search-mcp/Dockerfile`. The `postup` hook deploys the
real image after Bicep creates the bootstrap Container App. The API receives:

* `WEB_SEARCH_ENABLED=true`
* `WEB_SEARCH_MCP_URL=<internal-container-app-url>`
* `WEB_SEARCH_MCP_API_KEY=<secretref>`

The deployment exports `AZURE_WEB_SEARCH_MCP_CONTAINER_APP_NAME` and
`AZURE_WEB_SEARCH_MCP_URL` for validation and operations.

## Local Validation

Run the focused package tests and lint checks:

```powershell
cd planetary-explorer/web-search-mcp
python -m pytest -q
python -m ruff check src tests
```

Start the service with an existing Foundry project and Azure credential:

```powershell
$env:FOUNDRY_PROJECT_ENDPOINT = "https://<account>.services.ai.azure.com/api/projects/<project>"
$env:FOUNDRY_MODEL = "gpt-4o"
python -m web_search_mcp.server
```

Endpoints:

* `GET /health` for process liveness
* `GET /ready` for required configuration
* `POST /mcp` for Streamable HTTP MCP

## Security and Data Boundary

The Container App has internal-only ingress. Its identity receives
Foundry-scoped roles and uses the `https://ai.azure.com/.default` token scope.
Tool calls are read-only, queries are limited to 500 characters, output tokens
are bounded, and replicas are capped at three.

> [!IMPORTANT]
> Microsoft Foundry Web Search uses Grounding with Bing Search. Search queries
> leave the Azure compliance and geographic boundary, the Microsoft Data
> Protection Addendum does not apply to that data, and web-grounding calls
> incur additional usage charges. The service sends the explicit search query
> and tool parameters only. It does not append user IDs, tokens, conversation
> history, or map-state metadata.