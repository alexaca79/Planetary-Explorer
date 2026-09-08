---
title: Microsoft Fabric Integration
description: Configure app-identity access to existing Fabric data and understand the current connector's limits.
ms.date: 2026-09-08
---

## Scope and Authentication

Fabric is optional and requires no local GPU. The root deployment can create
a capacity, but does not create or populate workspaces, lakehouses, semantic
models or all required tables. See the [deployment resource matrix](../../documentation/deployment.md#resources-and-responsibilities).

[fabric_client.py](fabric_client.py) authenticates as the **backend service**.
It uses an explicitly configured service principal when all its credentials
are present; otherwise it uses `DefaultAzureCredential`, including managed
identity in Azure and the developer identity locally. Its compatibility
function `exchange_user_token` ignores the supplied user assertion.

Application sign-in is separate from Fabric authorization. Do not claim that
this connector applies Fabric RLS/OLS as the signed-in user. Data visible to
the backend identity can be shared among authenticated app users. Use this
path only for appropriately authorized app-scoped reference data; per-user
data isolation needs a separate reviewed implementation.

## Create or Reference the Data

1. Select an existing Fabric capacity/trial and a workspace, or create them
   through approved Fabric administration steps.
2. Create a lakehouse, ingest the required authoritative data and verify its
   table names/schemas. Bundled Canadian records are explicitly synthetic.
3. Grant the API managed identity the minimum workspace/item/OneLake access
   required by the selected APIs. Tenant policy may require enabling service
   principal use. The root Bicep template does not grant this workspace access.
4. Set `ENABLE_FABRIC=true`, `FABRIC_WORKSPACE_ID` and `FABRIC_LAKEHOUSE_ID`
   in azd. Runtime names are `PE_FEATURE_FABRIC`,
   `FABRIC_LAKEHOUSE_WORKSPACE_ID` and `FABRIC_LAKEHOUSE_ID`.
5. Set `FABRIC_TENANT_ID` or `AZURE_TENANT_ID` on the backend and verify a
   real read using that backend identity, not only an operator's browser.

For new capacity provisioning, additionally set `DEPLOY_FABRIC_CAPACITY=true`
and `FABRIC_ADMINISTRATORS` to a JSON array. Workspace assignment, item
creation and data ingestion remain separate actions. An existing
`FABRIC_CAPACITY_RESOURCE_ID` is an informational reference; it does not
automatically associate a workspace with that capacity.

## Runtime Configuration

| Setting | Purpose |
| --- | --- |
| `FABRIC_TENANT_ID` or `AZURE_TENANT_ID` | Tenant/configuration prerequisite |
| `FABRIC_CLIENT_ID` and `FABRIC_CLIENT_SECRET` | Optional service-principal credentials; both required to select this path |
| `FABRIC_API_ENDPOINT` | Defaults to `https://api.fabric.microsoft.com` |
| `FABRIC_PBI_API_ENDPOINT` | Defaults to `https://api.powerbi.com` |
| `FABRIC_DOC_SEARCH_URL` | Existing Azure AI Search endpoint for document lookup |
| `FABRIC_DOC_SEARCH_INDEX` | Existing populated index, default `planetary-explorer-docs` |
| `FABRIC_DOC_SEARCH_KEY` | Optional protected Search credential for this connector |

Do not commit credentials or print them in diagnostics. Prefer managed
identity. Sovereign endpoints and audiences require explicit validation;
changing one URL alone does not make the full integration sovereign-ready.

## API Surface and Limits

| Route | What It Establishes |
| --- | --- |
| `/api/fabric/status` | Configuration presence, not successful authorization or populated data |
| `/api/fabric/workspaces` | Workspaces visible to the backend identity |
| `/api/fabric/workspaces/{ws}/lakehouses` | Lakehouses visible to that identity |
| `/api/fabric/lakehouses/{ws}/{lh}/schema` | Best-effort table enumeration |
| `/api/fabric/query` | Experimental query bridge, not a validated Lakehouse T-SQL implementation |
| `/api/fabric/search_documents` | Existing Search index lookup; no index provisioning or ingestion |

The current `execute_sql` implementation sends the query to Power BI
`executeQueries`, which expects DAX and a semantic-model ID. A lakehouse ID is
not generally that ID, and arbitrary T-SQL is not supported by this route.
Do not use it as proof of a working SQL analytics connection. Use a verified
Fabric SQL/TDS or semantic-model integration for production query workloads.

The UI's stored workspace/lakehouse selection is a convenience, not an
authorization boundary. Test positive and denied data access before exposing
an integration to users. Disabled or unauthorized workflows must remain
explicitly unavailable rather than silently passing against seed data.