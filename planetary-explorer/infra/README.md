---
title: Planetary Explorer Infrastructure Reference
description: Explain template scope, CPU defaults, supported resource adoption and the distinction between provisioning and application publishing.
ms.date: 2026-09-08
---

## Canonical Deployment Instructions

Use the [deployment guide](../../documentation/deployment.md) for a new
environment or an existing-resource update. Both azd manifests load
[main.bicep](main.bicep) and [main.parameters.json](main.parameters.json).

The parameter file contains azd substitutions such as
`${DEPLOY_GEOFM=false}`. It is **not** a ready-to-submit ARM parameter file:
azd resolves those expressions first. For direct ARM deployments, supply
concrete Bicep parameters and an explicit subscription/region.

## Default Resource Contract

- CPU Container Apps environment and API, App Service frontend, registry,
  Azure Maps and monitoring
- Foundry account/projects, GPT-4o and GPT-4o-mini, storage and Key Vault
- Chat history Cosmos DB and artifact storage unless `DEPLOY_CHAT_HISTORY=false`
- GPU, premium chat models, Fabric, private catalog integration, CPU weather,
  Web Search and private endpoints are opt-in
- Dedicated ACR build pool defaults to zero; private builds need an explicitly
  configured network-reachable build path

See the [complete create-or-reference matrix](../../documentation/deployment.md#resources-and-responsibilities).
AI Search indexes, Fabric workspaces/lakehouses and private GeoCatalog data
are not created by the root template. Existing endpoint references require
separate permissions and data validation.

## Existing Resources

The resolver adopts exact API/Web App names and the API's Container Apps
environment in `rg-<AZURE_ENV_NAME>`. It rejects ambiguous candidates and
moving an existing Web App to a different plan. It does not import an
arbitrary deployment wholesale.

Other template modules are still reconciled by `azd provision`. Preserve the
original environment name and region to retain stable names. For updates
that must not reconcile infrastructure, deploy only selected applications
and compare protected settings before and after.

## Infrastructure-Only Script

[deploy-infrastructure.ps1](../../deploy-infrastructure.ps1) validates region
and model availability and provisions infrastructure. A fresh API requires
an explicit auth choice, for example from the repository root:

```powershell
.\deploy-infrastructure.ps1 -EnvironmentName '<environment>' -Location '<approved-region>' -EnableAuthentication -MicrosoftEntraClientId '<client-id>' -MicrosoftEntraTenantId '<tenant-id>'
```

Authenticate to the exact tenant/subscription first. This is not a substitute
for building and publishing the API/frontend. A bootstrap image is only an
initialization step. Use the root azd workflow for an integrated application
deployment instead of combining unrelated scripts.

The PowerShell switches/environment aliases differ from azd's uppercase
bindings. In particular, `-EnableFabric` does not create populated tenant
tables. Do not assume an option supported by one path is automatically an
input to another path.

## Validation

```powershell
python -m pytest scripts/tests -q
az bicep build --file planetary-explorer/infra/main.bicep --stdout > $null
```

Run these from the repository root. Before provisioning, review ARM
validation/what-if against the exact selected subscription, region and
concrete parameters. Local compilation cannot reserve quota or approve
policy exceptions. After publishing, check real revisions, non-placeholder
images, port 8080, health probes, identity grants and workflow evidence.

The CPU weather service uses internal ingress and `/health`. API probes use
`/api/health`; Web Search and GeoFM additionally use `/ready`. GPU worker
minimum replicas must remain zero outside explicitly approved work.

## Security and Recovery

Use managed identity for Azure data access and registry pulls. Do not enable
registry admin credentials or print keys to diagnose deployment. Do not dump
all deployment outputs: the template currently includes a Maps key output.

Private endpoints require DNS, operator/build-agent connectivity, and runtime
identity grants. Reprovisioning is not inherently non-disruptive; inspect the
plan before changing network or authentication flags. Preserve prior image
digests and frontend artifacts for rollback. Delete a resource group only
after confirming ownership and explicit cleanup authorization.