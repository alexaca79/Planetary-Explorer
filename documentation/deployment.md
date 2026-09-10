---
title: Deployment and Existing Resource Guide
description: Deploy a non-GPU Planetary Explorer environment or explicitly connect existing services, with readiness checks and optional integrations.
ms.date: 2026-09-10
---

## Choose a Deployment Path

| Goal | Path | Azure Changes |
| --- | --- | --- |
| Run the UI and develop locally | [Local development](../LOCAL_DEV_CONTAINER_DEVELOPMENT.md) | None unless you call configured services |
| Create a complete baseline application | Root `azd up`, below | Provisions selected resources, publishes web/API and enabled optional services |
| Update an existing environment | [Reuse and application updates](#reuse-and-application-updates) | Selective application deployment; provisioning is separate |
| Manage infrastructure separately | [Infrastructure reference](../planetary-explorer/infra/README.md) | Template reconciliation; application publishing is still required |
| Use GitHub Actions | [Fork CI/CD](#fork-cicd) | Only after explicit workflow authorization |

Use one environment per resource group. Resource names are derived from the
subscription, environment name, and region unless a supported exact-name
input is supplied. The root template targets `rg-<AZURE_ENV_NAME>`; it is not
a general-purpose importer for arbitrary resource groups.

## Non-GPU Baseline

No GPU quota, VM, CUDA installation, or GPU worker is needed for the web UI,
API, public STAC loading, raster sampling, image analysis, terrain, mobility,
climate workflows, or CPU weather adapter. AI answers still require a hosted
model service with quota and permissions. Hosted model APIs are not local
CPU inference and still incur usage charges.

Keep `DEPLOY_GEOFM=false` and `GEOFM_ENABLED=false` to exclude PlanAura GPU
deployment and calls. PlanAura Foundation Change has no supported CPU
equivalent in this repository. Its [GPU walkthrough](geofm-foundation-change.md)
is a separate opt-in, not a prerequisite for the baseline.

Forecast has two non-GPU-hosting choices: publish the CPU adapter or point to
existing scoring endpoints. The adapter implements Aurora, Earth-2 FCN, and
MAI Weather contracts using operational NWP data and disclosed synthetic
fallbacks. It does **not** run those native models. An external native model
endpoint can use GPU infrastructure owned elsewhere.

## Resources and Responsibilities

| Component | Baseline Provisioning | Existing Resource or Required Follow-Up |
| --- | --- | --- |
| Resource group | `rg-<environment>` | Reconcile this group only; inspect the plan before provisioning |
| Container Apps environment | Created unless adopted with the API | Existing environment must have suitable networking and workload profiles |
| API Container App | Created with a bootstrap image, then published by `azd deploy api` | Resolver adopts an exact compatible API; retain its identity and network settings |
| Web App and App Service plan | Created, then frontend ZIP published | Resolver adopts an existing Web App and its current plan; no automatic plan move |
| Container Registry | Created or reconciled under the template's stable name | Arbitrary BYO registry is not an infrastructure input; app-only updates can use an existing accessible registry |
| Log Analytics | Created or reconciled | Verify retention and diagnostics; a created workspace alone does not prove traces arrive |
| Foundry account and projects | Created by `DEPLOY_AI_FOUNDRY=true` | Set it false and provide both model and project endpoints; grants and deployments remain operator-owned |
| Chat models | GPT-4o and GPT-4o-mini with Foundry | Existing endpoints need these deployment names; premium models require explicit flags and quota |
| Embeddings | Provisioned with Foundry unless disabled | Required only for retrieval features that use embeddings |
| Azure Maps | Created or reconciled | Runtime needs its configured key; local no-key fallback has navigation only, not Azure-canvas Image Analysis |
| Key Vault and Foundry storage | Created with Foundry | This template does not adopt arbitrary vault/storage accounts by name |
| Chat history | Cosmos DB, database/container and artifact storage when `DEPLOY_CHAT_HISTORY=true` | Requires authenticated users and data-plane roles; set false when not needed |
| CPU weather adapter | Off by default | `DEPLOY_WEATHER_STUB=true` publishes the real CPU image; otherwise supply provider URLs |
| Web Search MCP | Off by default | Publish explicitly or connect an existing protected MCP endpoint; test actual grounding |
| Code Interpreter | Off by default | Set `CODE_INTERPRETER_ENABLED=true` on a compatible API build; uses the existing provider's managed sandbox, with additional charges |
| Fabric | Off by default | Existing populated workspace/lakehouse and backend identity grants required; capacity creation alone does not create data |
| Private GeoCatalog | Not created | Supply an authorized MPC Pro STAC endpoint and exact asset hosts |
| AI Search | Not created by the root template | Create or reference a service, populated indexes, and runtime identity permissions separately |
| Private endpoints and DNS | Off by default | Opt in when required by policy; build agents and operators need network reachability |
| GeoFM | Off by default, GPU-dependent | Separate explicit deployment or existing control endpoint with matching keys and network access |
| Teams/M365 surfaces | Not part of baseline publishing | Tenant app registration, manifest installation, API authorization and capability testing are separate |
| Legacy general MCP template | Not a supported baseline component | Contains mock tools; see [its status](../planetary-explorer/mcp-server/README.md) |

No template automatically creates your tenant's private datasets, assigns a
Fabric workspace to a capacity, populates every Search index, installs a
Teams app, or proves data availability at every Canadian point and date.

## Prerequisites

- A fork you control, Python 3.11, Node.js 20.19+ or 22.12+, PowerShell 7 on
  Windows, Azure CLI with Bicep/Container Apps support, and Azure Developer CLI
- Docker for local container builds; azd remote builds use the configured ACR
- Azure management permissions to create the selected resources and narrowly
  scoped role-assignment permission for their managed identities
- A permitted region and quota for App Service, Container Apps, ACR and hosted
  models; optional GPU/Fabric services have additional requirements
- An Entra app registration for the chosen authentication flow, redirect URI,
  token audience, tenant and authorized users

Use an isolated CLI profile for each tenant. Do not print all environment
values, keys, access tokens, or signed asset URLs into logs or issue reports.

```powershell
$tenantId = '<tenant-id>'
$subscriptionId = '<subscription-id>'
$env:AZURE_CONFIG_DIR = "$HOME/.azure-tenants/<tenant-alias>"
$env:AZD_CONFIG_DIR = "$HOME/.azd-tenants/<tenant-alias>"
az login --tenant $tenantId
az account set --subscription $subscriptionId
azd auth login --tenant-id $tenantId
az account show --query '{tenant:tenantId,subscription:id,name:name}' -o json
```

Confirm the returned tenant and subscription before any write. Authentication
does not grant missing roles or create services. If a policy denies a service
or public networking, satisfy the policy; do not disable it to finish a demo.

### Configure Application Sign-In

Use the official [App Service Microsoft identity-provider procedure](https://learn.microsoft.com/azure/app-service/configure-authentication-provider-aad)
for an existing single-tenant app registration. This is separate from the
deployment identity used by azd or GitHub Actions.

1. Create or select the Entra registration and record its client and tenant
  IDs. Restrict the supported tenant and assign the intended users/groups
  according to your access policy.
2. On the Web App's Microsoft identity provider, use that registration and
  the Web redirect URI `https://<actual-web-host>/.auth/login/aad/callback`.
  Once provisioning resolves the hostname, confirm it on both the Web App
  and registration; retain any other legitimate redirect URIs.
3. Complete the provider's confidential-client credential configuration with
  a protected secret setting or a supported managed-identity federation.
  The repository hook does not create or rotate this credential. Do not put
  it in Vite variables, source, shell history or model-visible messages.
4. Enable the token store and require sign-in. The frontend reads
  `/.auth/me` and forwards an application-bound token to the API. Verify the
  actual flow after deployment; never share the response's token values.
5. The API performs in-process JWT signature, expiry, tenant and audience
  validation. Its allowlist uses the configured client ID and
  `api://<client-id>`; a Microsoft Graph token is not an API credential.
  Keep `DISABLE_AUTH=false` and `TRUST_EASYAUTH_HEADER=false`. Do not add a
  second, mismatched Container Apps Easy Auth layer.

The auth hook briefly makes API ingress internal while it configures and
checks security, then restores external access. It can request a registration
redirect update; application-owner permissions may be required. Failure must
stay closed until corrected. A created registration or successful hook is
not a substitute for a real sign-in and denied-request test.

## Create a CPU Environment

Run from the repository root. Use your own fork as the clone/PR destination.

```powershell
azd init
azd env set AZURE_SUBSCRIPTION_ID $subscriptionId
azd env set AZURE_LOCATION '<approved-region>'
azd env set ENABLE_AUTHENTICATION true
azd env set PUBLIC_DEMO_MODE false
azd env set MICROSOFT_ENTRA_CLIENT_ID '<application-client-id>'
azd env set MICROSOFT_ENTRA_TENANT_ID $tenantId
azd env set DEPLOY_GEOFM false
azd env set GEOFM_ENABLED false
azd env set DEPLOY_GPT5 false
azd env set DEPLOY_GPT56 false
azd env set ENABLE_FABRIC false
azd env set ENABLE_MPC_PRO false
azd env set DEPLOY_WEB_SEARCH_MCP false
azd env set ACR_AGENT_POOL_COUNT 0
azd env set DEPLOY_WEATHER_STUB true
```

The weather choice above enables Forecast without GPU hosting. Set it false
for a smaller baseline and supply an existing provider URL if Forecast is
required. Chat history defaults on; `azd env set DEPLOY_CHAT_HISTORY false`
omits its Cosmos deployment and disables history wiring.

For private endpoints, also set `ACR_AGENT_POOL_COUNT 1` before provisioning,
unless you have verified another private build path. This creates a billed,
always-on VNet build pool. Direct ARM and GitHub workflow deployments default
to one pool VM only when private endpoints are explicitly enabled; the public
CPU baseline remains at zero. Do not open the registry firewall to build.

Run local gates before provisioning:

```powershell
python -m pytest scripts/tests -q
az bicep build --file planetary-explorer/infra/main.bicep --stdout > $null
azd show
```

The preprovision hook validates azd environment settings, resolves existing
API/frontend targets and requires an explicit authentication mode. The root
and nested manifests use the same parameter template. Set uppercase
environment variables, not camelCase Bicep parameter names.

After reviewing the intended resource group, location, quotas, network access
and costs, `azd up` provisions, packages and deploys web/API, then publishes
only explicitly enabled optional services. A CPU baseline does not publish
GeoFM, even if old GPU resource names remain in local environment outputs.

```powershell
azd up
```

`azd provision` alone is **not** a finished deployment: bootstrap images may
remain, and the frontend has not been built or published. Reprovisioning can
reset application configuration; rerun the appropriate application steps and
readiness checks afterward. Deployment duration depends on quota, build and
identity propagation, not a fixed one-hour guarantee.

For a disposable public demo only, explicitly choose `PUBLIC_DEMO_MODE=true`
and `ENABLE_AUTHENTICATION=false`. This makes protected API routes public and
disables per-user history. It is not a workaround for authentication failures
and is not suitable for private tenant data.

## Reuse and Application Updates

Keep the original environment name, region and resource group. Changing them
changes generated resource names and can create another stack.

```powershell
azd env select '<existing-environment>'
azd env refresh
azd env set API_CONTAINER_APP_NAME '<existing-api-name>'
azd env set AZURE_CONTAINER_APP_NAME '<existing-api-name>'
azd env set AZURE_CONTAINER_APP_URL 'https://<existing-api-host>'
azd env set AZURE_WEB_APP_NAME '<existing-web-app-name>'
azd env set AZURE_APP_SERVICE_PLAN_NAME '<existing-plan-name>'
```

The resolver checks resources in `rg-<environment>` and rejects ambiguous
targets or a conflicting Web App plan. Adoption skips reconciliation of the
API, Web App and adopted Container Apps environment, but **does not** turn
`azd provision` into an application-only operation: other modules are still
created or reconciled.

`API_CONTAINER_APP_NAME` is a provisioning/resolver input.
`AZURE_CONTAINER_APP_NAME` is the service deployment target, and
`AZURE_CONTAINER_APP_URL` is the frontend build input. The preprovision
resolver does not run during `azd deploy api`; refresh or explicitly set and
verify all three for an application-only update. Never substitute an example
host for the existing app's actual ingress hostname.

For code-only updates, verify exact deployment outputs and deploy named
services instead of running `azd up` or `azd provision`:

```powershell
azd env get-value AZURE_RESOURCE_GROUP
azd env get-value AZURE_CONTAINER_APP_NAME
azd env get-value AZURE_WEB_APP_NAME
azd env get-value AZURE_CONTAINER_APP_URL
azd deploy api
azd deploy web
```

These deploy commands run service hooks and can reconcile selected runtime
settings. For a strict image/ZIP-only release that must preserve every
setting, use explicit `az containerapp update --image <digest>` and
`az webapp deploy --type zip` against verified names; capture configuration
before and compare it afterward. The frontend ZIP must be built with
`VITE_API_BASE_URL` or `AZURE_CONTAINER_APP_URL` set to the actual API HTTPS
origin. App Service settings cannot repair an already compiled wrong origin.

An endpoint reference is not permission to redeploy its owner. Existing
external services must already have compatible versions, identity grants,
DNS/network reachability and data. The root template does not grant access to
arbitrary external projects, registries, catalogs or Fabric workspaces.

### Existing AI Services

```powershell
azd env set DEPLOY_AI_FOUNDRY false
azd env set AZURE_OPENAI_ENDPOINT 'https://<account>.openai.azure.com'
azd env set EXISTING_AI_PROJECT_ENDPOINT 'https://<account>.services.ai.azure.com/api/projects/<project>'
```

Both endpoints are required. Supply existing `gpt-4o` and `gpt-4o-mini`
deployments with tool/vision support and grant the API managed identity the
appropriate OpenAI inference and project agent permissions. The template's
[role module](../planetary-explorer/infra/shared/foundry-role.bicep) grants
`Cognitive Services OpenAI User`, `Azure AI Developer`, and
`Cognitive Services User` at the specific Foundry account scope. For an
existing resource, its owner must supply the equivalent permissions needed
for the selected API and project, not subscription-wide Contributor as a
substitute. Project/service versions can require additional project-scoped
roles; verify a real agent call with the actual API identity. Use the same
identity and project to test a real request after deployment. Do not paste
credentials into an endpoint URL.

### Weather Provider References

```powershell
azd env set DEPLOY_WEATHER_STUB false
azd env set AURORA_ENDPOINT_URL 'https://<existing-provider>'
azd env set EARTH2_FCN_ENDPOINT_URL 'https://<existing-provider>'
azd env set MAI_WEATHER_ENDPOINT_URL 'https://<existing-provider>'
azd env set MAI_WEATHER_SCORE_PATH '/mai-weather/score'
```

Configure only the providers you have. Explicit URLs override the generated
CPU adapter URL. Match the adapter's [request/response contracts](../planetary-explorer/weather-stub-server/README.md)
and the connectors' authentication requirements. `FORECAST_AGENT_ENABLED=false`
disables analysis without deleting provider infrastructure. Verify native
versus adapter provenance in the returned dossier.

### Private Data and Other Integrations

- MPC Pro: `ENABLE_MPC_PRO=true`, `MPC_PRO_STAC_URL`, and
  `MPC_PRO_ASSET_HOSTS`; authorize the API identity and ingest imagery first.
  [Private catalog sidecar guide](../planetary-explorer/mpc-mcp-sidecar/README.md)
- Fabric: `ENABLE_FABRIC=true`, `FABRIC_WORKSPACE_ID`,
  `FABRIC_LAKEHOUSE_ID`, and an optional `FABRIC_CAPACITY_RESOURCE_ID`.
  Populate required tables and grant the backend identity access. A new
  capacity additionally requires `DEPLOY_FABRIC_CAPACITY=true` and a JSON
  array in `FABRIC_ADMINISTRATORS`. Workspace creation/assignment and data
  ingestion are separate. [Fabric setup](../planetary-explorer/container-app/FABRIC.md)
- Web Search: `DEPLOY_WEB_SEARCH_MCP=true` and a protected
  `WEB_SEARCH_MCP_API_KEY` of at least 32 characters; existing Foundry needs
  `WEB_SEARCH_FOUNDRY_ACCOUNT_NAME` and `WEB_SEARCH_FOUNDRY_PROJECT_ENDPOINT`.
  To connect without deploying, use `WEB_SEARCH_ENABLED=true` and
  `WEB_SEARCH_MCP_URL` with the matching key. [Web Search](../planetary-explorer/web-search-mcp/README.md)
- Code Interpreter: publish a compatible API build, then set
  `CODE_INTERPRETER_ENABLED=true` on the API Container App. This is a runtime
  setting, not a Vite variable or an instruction to run Python on the API host.
  The existing Agent Service and Responses paths register a managed sandbox
  only when enabled. Verify the chosen model supports it and inspect actual
  `structured.code_interpreter` execution logs. Provider sandbox charges apply
  in addition to tokens. The reference workflow uses text/JSON, not an implemented
  upload/download UI. Set the flag false and restart the API to disable it;
  verify the setting after future provisioning. See the
  [two-tool usage example](get-started-playbook.md#use-web-search-and-code-interpreter).
- Existing GeoFM: `DEPLOY_GEOFM=false`, `GEOFM_ENABLED=true`,
  `GEOFM_MCP_URL`, and distinct matching `GEOFM_MCP_API_KEY` and
  `GEOFM_OWNER_SIGNING_KEY`. This avoids provisioning another GPU worker,
  but approved analysis still executes GPU work at the existing service.
  Private Blob artifacts require an authorized network path in addition to
  their short-lived download authorization. A valid link does not override
  storage firewall rules. In the September 9 test, external downloads returned
  403 while in-network artifact hashes and the in-app polygon were verified.
  [GeoFM operator guide](../planetary-explorer/geofm-sidecar/README.md)
- Search, Resilience and Site Intel: point their documented runtime settings
  at populated services and verify identity access. A feature flag, capacity
  ID or health response is not evidence of authorized data access.

Keep secrets in a secret store or ignored local configuration. Never publish
the full azd environment. Do not enable an optional feature to make a missing
prerequisite appear to pass.

## Readiness Gates

After application publishing, check all of the following:

1. Exact resource names, tenant, subscription, region and intended ownership
2. Non-bootstrap images, ready revisions, correct ports/probes, intended
   traffic weights and unchanged authentication/networking
3. Frontend bundle containing the correct API origin; real map pixels, zoom
   and pin placement on desktop and mobile
4. `/api/config` capability flags and `/api/health`, followed by an
   authenticated model request with actual tool evidence
5. Existing-service identity grants and network paths; populated Search,
   Fabric or private STAC data where enabled
6. [Get Started verification](get-started-playbook.md#reproduce-the-release-checks), with
   pass, unavailable-data, disabled-capability and authentication blocks
   recorded separately

The strict verifier binds results to API/weather image digests, revisions and
frontend bundle hash. Do not call a release verified until those identities
match before and after testing. Keep GeoFM at zero replicas and do not submit
GPU work in a non-GPU validation run. Private-only or GPU workflows can remain
explicitly untested; the baseline does not depend on them.

## Fork CI/CD

Use your fork's workflows and environment protection rules. Default PR and
push destinations should remain your fork; merge only on explicit direction.
The existing workflow uses OIDC, requiring tenant/client/subscription IDs,
federated trust for the exact fork/environment and appropriate Azure roles.
Creating GitHub secrets does not create the trust or grant roles.

Inspect [.github/workflows](../.github/workflows) before enabling a workflow.
The azd bindings in this guide are not automatically GitHub workflow inputs.
Keep automatic deployment off while reviewing code. Do not assume the legacy
MCP deployment job is a supported agent service or use a hello-world image as
proof of application readiness.

## Validation Limits

Local tests and Bicep compilation validate configuration and source behavior;
they do not reserve quota, satisfy Azure Policy, grant external permissions,
or prove a fresh deployment works in every tenant. Use ARM validation and a
reviewed what-if before infrastructure writes, then complete the live gates.
Prices and quotas change. A scale-to-zero CPU or GPU service can still have
storage, registry, network and other standing costs.