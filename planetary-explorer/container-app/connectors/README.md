---
title: External Platform Connectors
description: Identify connector ownership, service configuration and limits without mistaking a configured URL for a provisioned dependency.
---

## Connector Responsibilities

These modules wrap selected external services. They do not provision Azure
resources, grant access, create datasets or guarantee live availability.
Existing agents also call other clients directly; this package is not yet the
only outbound access layer.

| Module | Interface and Prerequisites |
| --- | --- |
| `weather` | Capability-based provider registry; activates configured scoring endpoints with their auth contracts |
| `mpc_pro` | Re-exports the catalog MCP client; requires `USE_MPC_MCP`, `MPC_MCP_URL`, private catalog access and compatible tools |
| `fabric` | Re-exports functions such as `list_workspaces`, `list_lakehouses`, `get_lakehouse_schema` and `execute_sql`; not a `FabricClient` class |
| `ai_search` | `AiSearchClient.from_env()`, `search`, `get_document`; requires a populated index and an authorized identity or protected key |
| `openmeteo` | `OpenMeteoClient.forecast`; public operational forecast API with an in-process cache |
| `mcp_registry` | Re-exports `McpRegistry` and `TracedMcpClient` from `mcp_runtime`, including confirmation and tracing |

## Configuration and Data

Use the [deployment/resource guide](../../../documentation/deployment.md)
to choose create versus reference. For weather, the [CPU adapter](../../weather-stub-server/README.md)
is a non-GPU option, not native foundation-model inference. Providers must
preserve source and synthetic-fallback metadata.

Fabric uses the backend identity; see [FABRIC.md](../FABRIC.md) for grants and
query limitations. Search expects `AZURE_SEARCH_ENDPOINT`,
`AZURE_SEARCH_INDEX`, and identity permissions or `AZURE_SEARCH_KEY`.
The root stack does not create/populate every index. Inspect the specific
consumer's required schema before ingesting documents.

Register only authorized MCP endpoints. Tool discovery is not permission to
execute a mutation; retain confirmation gates and never log bearer tokens,
keys or signed asset URLs. No connector change should bypass a disabled
feature or turn missing data into a fabricated success.

## Extending Connectors

Prefer existing typed interfaces and tests. Add bounded timeouts, classify
retry safety before dispatch, and preserve source provenance. Test both a
successful dependency response and unavailable/unauthorized behavior before
advertising the feature as usable.