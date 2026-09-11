---
title: Fan-Out Planner Template
description: Starting point for a model-backed fan-out agent, with implementation and connector prerequisites.
---

## Template Status

A reference agent that takes a user question, asks the LLM to decompose
it into N independent steps, and runs them concurrently using the
framework's deadlock-safe fan-out executor.

## Copy & rename

Run from the inner `planetary-explorer/` directory, not the repository root:

```powershell
python scripts/new_agent.py weather_research --template fan_out_planner
```

That produces `container-app/agents/weather_research/` with the class
renamed to `WeatherResearchAgent` and all package references rewritten.

## Patterns Illustrated

- Plan synthesis with `response_format={"type": "json_object"}`.
- gpt-5 family sampling-param sanitisation (built into `LlmClient`).
- Concurrent step execution capped by `max_concurrency`, per-step
  timeout, per-step error capture (no one failure kills the batch).
- Optional catalog MCP tool calls per step; Public is the default, and each call surfaces as
  `tool_call` / `tool_result` SSE events for the trace drawer.
- OBO assertion plumbing if you need Fabric / AI Search inside a step.

## What to customise

Override `run_step()` to implement real per-step logic. Plan generation
requires a configured hosted LLM; MCP steps require an authorized reachable
catalog service. Other steps are demonstration echoes, not analysis.

This is a scaffold, not a turnkey offline agent. Its explicit
`OBOContextMixin` constructor call must be reconciled with the mixin's actual
interface before using the generated agent. Test initialization, denied
access, timeouts and provenance before registering it in a running service.
No GPU is needed unless the implemented steps invoke a GPU-dependent backend.
