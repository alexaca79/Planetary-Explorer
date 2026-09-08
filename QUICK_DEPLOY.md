---
title: Quick Deploy - Planetary Explorer
description: Start a non-GPU deployment or update an existing environment without confusing infrastructure with application readiness.
ms.date: 2026-09-08
---

## Start Here

Follow the [deployment and existing-resource guide](documentation/deployment.md)
for the current commands, prerequisites and resource ownership matrix. Run
commands from the repository root and use your own fork.

| Need | Read |
| --- | --- |
| No Azure provisioning | [Local development](LOCAL_DEV_CONTAINER_DEVELOPMENT.md) |
| New CPU-hosted environment | [Create a CPU environment](documentation/deployment.md#create-a-cpu-environment) |
| Use existing API, frontend or models | [Reuse and application updates](documentation/deployment.md#reuse-and-application-updates) |
| Forecast without GPU quota | [Non-GPU baseline](documentation/deployment.md#non-gpu-baseline) and [weather adapter](planetary-explorer/weather-stub-server/README.md) |
| Fabric, private imagery or external scoring | [Resource responsibilities](documentation/deployment.md#resources-and-responsibilities) |
| Infrastructure-only workflow | [Infrastructure reference](planetary-explorer/infra/README.md) |
| Prove the deployment works | [Readiness gates](documentation/deployment.md#readiness-gates) and [Get Started playbook](documentation/get-started-playbook.md) |

## What the Default Path Does

The root azd workflow provisions the selected stack, builds and publishes the
web UI and API, and publishes explicitly enabled optional services. It does
not deploy a GPU worker by default. The CPU weather adapter is available as an
opt-in; managed model APIs still need quota and permissions.

Choose authentication before running `azd up`. A fresh environment must use
either configured Entra authentication or an explicitly approved public demo
mode. No-argument infrastructure scripts are not a complete authenticated
application deployment.

`azd provision` alone can leave bootstrap images. A successful resource
deployment is not proof that model access, private data, map rendering or
optional services work. Every enabled component must be published or linked
to a compatible, authorized existing service, then tested.

## Existing Environments

Keep the original environment name and region. Resolve exact resource names
before writes; never select the first Container App in a group. Use named
application deployments for code updates and review infrastructure changes
separately. The frontend API origin is set at build time.

GitHub Actions requires OIDC trust, roles and environment protection in your
fork. Keep auto-deploy off until the workflow and target are reviewed. Do not
open or merge an upstream PR as a side effect of deployment work.

## Completion Criteria

Record actual application images/revisions and frontend bundle hash, verify
authentication and service access, and exercise the Get Started workflows.
Separate passes from missing data, disabled integrations, and sign-in gates.
GPU execution and tenant-private workflows require separate authorization
and prerequisites; they are not required for the non-GPU baseline.