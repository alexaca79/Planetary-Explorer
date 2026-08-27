---
title: Planetary Explorer GeoFM
description: PlanAura control-plane, worker, evidence, and deployment guidance
ms.topic: overview
---

## Capability

Planetary Explorer can submit bi-temporal HLS imagery to the PlanAura
geospatial foundation model for **change** analysis, and single-epoch Sentinel
imagery for **classification**. The AnalystAgent exposes seven tools:

* `list_geofm_models`
* `list_geofm_class_schemes`
* `compare_with_geofm`
* `classify_with_geofm`
* `get_geofm_run`
* `retry_geofm_run`
* `cancel_geofm_run`

Submission, retry, and cancellation use the existing MCP confirmation flow. Model work
continues after the browser or agent turn disconnects.
Standard chat uses the `/api/query/stream` endpoint so the approval card and
tool trace remain visible while the agent turn is paused.

### Profile registry

`policy.py` is a fail-closed registry. Unknown profiles raise; `BLOCKED` profiles
are refused; `CONDITIONAL` profiles require `GEOFM_ALLOW_CONDITIONAL`.

| Profile | Capability | Collections | Quality asset | AOI cap | Ships as |
|---|---|---|---|---|---|
| `planaura_hls` | change | `hls2-s30`, `hls2-l30` | `Fmask` | 15.36 km | `CONDITIONAL` |
| `planaura_classify_s2` | classify | `sentinel-2-l2a` | `SCL` | 15.36 km | `CONDITIONAL` |
| `planaura_classify_s1` | classify | `sentinel-1-rtc` (fuses `sentinel-2-l2a`) | `mask` | 5.12 km | `BLOCKED` |
| `planaura_classify_s3` | classify | `sentinel-3-olci-wfr-l2-netcdf`, `sentinel-3-slstr-wst-l2-netcdf` | `wqsf` | 153.6 km | `BLOCKED` |

Each AOI cap is `native_resolution_m × tile_size_pixels`, PlanAura's fixed 512-pixel
context window. The MCP surface adds `geofm_classify_aoi` (submit, owner-signed) and
`geofm_list_class_schemes` (read-only) alongside the existing tools.

Classification is **unsupervised**: PlanAura-1.0 is a masked-reconstruction backbone that
yields embeddings, not labels. Clusters are named from co-computed spectral signatures and
every result carries a non-suppressible "cluster-derived, not a validated land-cover
product" warning, its class-scheme ID, and per-class confidence. Moving a profile from
`BLOCKED` to `CONDITIONAL` requires a published validation report with per-class F1 and a
confusion matrix against held-out reference labels. The end-user walkthrough lives in
[`documentation/classification-mode.md`](../../documentation/classification-mode.md).

## Runtime boundary

The capability uses two isolated containers:

* The MCP control plane validates requests, persists run state in Blob Storage,
  and sends run IDs to Queue Storage
* The queue-scaled worker reads HLS assets, invokes PlanAura on a serverless T4
  GPU, and persists derived artefacts

The main API image does not install Torch or PlanAura. PlanAura remains pinned
to Python 3.10, Torch 1.12, CUDA 11.6, and the following immutable sources:

| Component          | Pin                                                                |
|--------------------|--------------------------------------------------------------------|
| Runtime repository | `NRCan/planaura`                                                    |
| Runtime commit     | `a880b26ce08a545b35d6afa431bace39842dd19d`                         |
| Model repository   | `NRCan/Planaura-1.0`                                                |
| Model revision     | `fbbabfdcc0d5e48f7bd05c79b512563cf337742f`                         |
| HLS checkpoint     | `Planaura-1.0-HLS.pth`                                             |
| SHA-256            | `cc3041600ec62bc5452f243304ca446c8793e65baf13440cc21c4cf8ba7199eb` |

The worker image downloads and verifies the checkpoint during its build. It
also verifies the same bytes before constructing the model.

A classifier head is verified the same way. `GEOFM_CLASSIFIER_HEAD_DIR` names the
build-time download directory and `GEOFM_CLASSIFIER_HEAD_PATH` the runtime artefact;
both size and SHA-256 are checked before the head is loaded. No approved supervised
head ships today, so the unsupervised clustering path is the only one available.

## Evidence contract

PlanAura produces measurements and spatial artefacts. The language model only
explains validated outputs.

Completed change runs return:

* Scalar distance and changed-area statistics
* Ranked GeoJSON polygons clipped to the requested AOI
* References and hashes for the distance COG, polygons, STAC item, and evidence
  manifest

Completed classification runs return `class_map` (paletted COG), `class_polygons`
(GeoJSON), `class_statistics` (per-class area, share, and mean confidence),
`stac_item`, and `evidence_manifest`. The manifest records the source item hashes,
the checkpoint hash, the classifier-head hash, and the class-scheme ID.

Raw pixels, band arrays, embedding tables, feature stacks, and logits are rejected
from MCP response payloads. The change metric is `1 - cosine similarity`, where larger
values represent stronger contextual change. Classification confidence is the
cluster-assignment margin `1 - d1/d2`; pixels below the requested minimum are withheld
rather than guessed.

## Local validation

Use Python 3.11 for the control-plane and model-free tests:

```powershell
Set-Location planetary-explorer/geofm-sidecar
python -m pytest tests -q
```

The GPU image requires a running Docker Linux engine and downloads a checkpoint
larger than 1 GB. The lightweight control image can be built independently:

```powershell
docker build --file Dockerfile --tag planetary-explorer-geofm:local .
```

## Azure deployment gates

The Bicep path is disabled by default. Before setting `deployGeoFm=true`:

1. Use isolated `AZURE_CONFIG_DIR` and `AZD_CONFIG_DIR` values, then verify the
   intended tenant and subscription.
2. Confirm that the target region reports
   `Consumption-GPU-NC8as-T4` from
   `az containerapp env workload-profile list-supported`.
3. Confirm Container Apps T4 quota for the subscription.
4. Confirm that Azure Container Registry remote builds can reach GitHub and
   Hugging Face. The two `azd deploy` commands build and push the images.
5. Set `geoFmMcpApiKey` and the distinct `geoFmOwnerSigningKey` to random values
   of at least 32 characters. The first authenticates MCP transport; the second
   binds submit, get, and cancel operations to an authenticated owner.
6. Set `deployGeoFm=true` and `geoFmAllowConditional=false`, then run the
   deployment commands below.
7. Verify `/health`, `geofm_list_models`, and `geofm_list_class_schemes` before
   allowing inference.
8. In a validation environment, enable the conditional profiles and run the
   pinned worker image against a known HLS pair and a known Sentinel-2 scene.
   Compare each output manifest with the expected checkpoint, classifier-head,
   and source-item hashes.
9. Enable `geoFmAllowConditional` in a production environment only after the
   GPU smoke test passes.
10. Optionally set `GEOFM_MAX_ACTIVE_RUNS_PER_OWNER` (default `3`) to cap
    concurrent GPU work per owner. Classification invites bulk use far more
    than pairwise change detection, so review this figure against the
    subscription budget before rollout.

The default `azd up` workflow deploys the existing web and API services only,
which keeps `deployGeoFm=false` environments unchanged. After provisioning an
environment with `deployGeoFm=true`, publish the optional services explicitly:

```powershell
azd env set DEPLOY_GEOFM true
azd env set-secret GEOFM_MCP_API_KEY
azd env set-secret GEOFM_OWNER_SIGNING_KEY
azd up
azd deploy geofm
azd deploy geofm-worker
```

An `azd provision` replaces optional service images with bootstrap images.
Run both named `azd deploy` commands again after changing GeoFM infrastructure
parameters such as `geoFmAllowConditional`.

The infrastructure uses a private MCP endpoint, a user-assigned managed
identity for each service, and a shared key between the backend and MCP
control plane. Blob data roles are scoped to the `geofm` container; the control
identity also receives Storage Blob Delegator at account scope so polling can
return five-minute read-only evidence links. The control plane receives
queue-send access, while the worker receives queue-processing
access on `geofm-jobs` and `geofm-poison`. Malformed, terminally failed, and
retry-exhausted messages are copied to the poison queue before the source is
acknowledged; failed quarantine leaves the original message unacknowledged. Both
identities receive AcrPull. When
private endpoints are enabled, Blob and Queue DNS zones are linked to the
Container Apps virtual network.