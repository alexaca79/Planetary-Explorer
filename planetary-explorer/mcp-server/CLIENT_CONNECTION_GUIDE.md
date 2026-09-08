---
title: MCP Client Connection Requirements
description: Distinguish stdio, Streamable HTTP and REST bridges, and configure protected clients only for verified services.
---

## Choose a Verified Service

Do not configure this directory's mock HTTP bridge as a production MCP server.
Use the [service-specific links](README.md) and confirm which transport the
chosen implementation supports.

- Stdio clients launch a local process and communicate over stdin/stdout.
- Streamable HTTP clients use an MCP endpoint with initialization, protocol
  negotiation, session handling and notifications.
- REST APIs are not automatically MCP, even if they accept JSON-RPC-shaped
  requests or have an endpoint named `/mcp`.

Use an SDK/client that handles the full handshake. Do not pipe an SSE response
directly into a JSON parser or assume `tools/list` proves backend authorization.

## Credentials and Configuration

For VS Code, use the current MCP configuration surface, normally
`.vscode/mcp.json`, and the selected server's documented transport. Keep
secrets in secure inputs or a credential store, not committed JSON or browser
JavaScript. See the [Resilience wrapper example](../../m365/mcp-server/README.md)
for a protected HTTP configuration.

Other clients vary in remote transport and authentication support. Consult
their current documentation rather than treating one client's configuration
schema as portable. Match the server's actual Bearer/API-key/OAuth policy.

Inbound MCP authorization and outbound backend authorization are separate.
A client token for the wrapper is not necessarily accepted by the API or
private data service. Configure and test both boundaries. Never publish
verbose HTTP traces that include Authorization headers or subscription keys.