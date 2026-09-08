---
title: General MCP Deployment Readiness
description: State the implementation and validation requirements before the experimental MCP template can be deployed for real users.
---

## Current Blockers

This template is not ready for a production deployment. The Docker entry point
uses a mock client; the stdio path has missing dependency/import prerequisites;
and the HTTP bridge lacks complete MCP initialization/session handling.
Deployment scripts in this folder do not resolve those implementation gaps.

## Required Gates Before Publishing

1. Replace mock results with real, authenticated backend calls and preserve
   numeric values, sources, dates and errors.
2. Use a supported MCP SDK with tests for initialize, initialized, tool
   discovery/calls, session reuse, cancellation and transport errors.
3. Protect inbound access and separately authorize the backend identity/token.
   Restrict CORS; test denied and missing credentials.
4. Build the actual application image, pin its digest and configure managed
   identity registry pull. Do not enable ACR admin credentials for convenience.
5. Resolve the exact resource group, app, port and endpoint from the chosen
   environment. Do not substitute an example hostname or select the first app.
6. Prove a real end-to-end call against the intended API, including unavailable
   private-data/model prerequisites. A health page or tool list is insufficient.

The wrapper host itself needs no GPU. A tool can invoke a GPU-dependent
backend capability, which requires separate authorization and cost controls.
Follow the [main deployment guide](../../documentation/deployment.md) for
supported CPU application hosting and existing-service references.

Keep local mock tests and production evidence separate. Do not relabel a mock
success, HTTP 200 or placeholder container as a validated agent workflow.