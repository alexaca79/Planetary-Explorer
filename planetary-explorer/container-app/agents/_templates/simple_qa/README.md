---
title: Simple Q&A Template
description: Model-backed agent scaffold and its external service prerequisites.
---

## Scope

Minimal MAF agent built on `_framework/` primitives.

## What it shows

| Pattern | Where |
|---|---|
| Single LLM endpoint resolution (AOAI vs Foundry) | `LlmClient.from_env()` |
| gpt-5 sampling-param stripping | inside `LlmClient.chat()` |
| OBO-bound downstream calls | `OBOContextMixin.fabric_token()` |
| Traced MCP tool invocation | `TracedMcpClient.from_mpc_public()` (default for agents; switch to `from_mpc_pro()` only when Pro-only features are needed) |

## Use it as a starting point

Run from the inner `planetary-explorer/` directory:

```bash
python scripts/new_agent.py weather_chat
```

That copies this directory to `container-app/agents/weather_chat/` and
rewrites the class name + imports.

The generated agent requires a configured hosted model endpoint and identity
permissions. Downstream Fabric/Search/MCP calls have their own access
contracts; the mixin example does not establish per-user authorization for
every connector. Verify initialization and real tool evidence before use.
CPU hosting is sufficient unless an added tool calls a GPU-dependent service.
