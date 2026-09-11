---
title: Experimental General MCP Template
description: Explain the legacy MCP template's mock behavior, CPU-only local scope and production blockers.
ms.date: 2026-09-08
---

## Status

This directory is an experimental template, not the production Planetary
Explorer agent runtime. Its Dockerfile starts [mcp_bridge.py](mcp_bridge.py),
which uses `MockMCPClient`. Several tools return fabricated demonstration
results. A successful request, health check or container deployment does not
establish real satellite, terrain or agent analysis.

The separate [server.py](server.py) uses stdio MCP and still references an
absent legacy router directory. Its requirements do not install the MCP SDK.
The HTTP bridge's `/mcp` endpoint is not a complete MCP initialization/session
implementation. Do not advertise either path as production-ready or as a
wrapper exposing every current agent.

## Non-GPU Scope

The template can run on CPU for local API/mock experiments. That does not
provide local model inference or configure a real backend. Tools that forward
requests need an explicitly configured, reachable and authorized Planetary
Explorer API. Merely setting model names on this wrapper cannot turn mock
results into measurements.

For the actual web/API deployment, use the
[non-GPU deployment guide](../../documentation/deployment.md). Current
service-specific integration documentation is separate:

- [Resilience MCP wrapper](../../m365/mcp-server/README.md)
- [MPC Pro catalog bridge](../mpc-mcp-sidecar/README.md)
- [Web Search MCP](../web-search-mcp/README.md)
- [GeoFM control and worker](../geofm-sidecar/README.md), optional GPU execution

Each integration has its own authentication, network, data and runtime
requirements. None is provisioned merely by registering an MCP URL in a client.

## Template Guides

- [Local CPU experiment](QUICK_START.md)
- [Client transport and authentication](CLIENT_CONNECTION_GUIDE.md)
- [Deployment readiness checklist](DEPLOYMENT_TESTING_GUIDE.md)

The old generic deployment examples are intentionally removed: they used
placeholder images, fixed tenant hosts, incomplete protocol requests and
browser-embedded keys. Keep this template off public ingress until the
implementation and its positive/negative tests satisfy the readiness checklist.