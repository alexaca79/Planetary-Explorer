---
title: Planetary Explorer Web UI
description: Develop and deploy the React/Vite frontend with the correct API origin and map prerequisites.
ms.date: 2026-09-08
---

## Local Development

The React 18/TypeScript UI uses Vite and a FastAPI Container App backend. It
does not require a GPU. From this directory, with Node.js 20.19+ or 22.12+:

```powershell
npm ci
$env:LOCAL_BACKEND_URL = 'http://localhost:8000'
npm run dev
```

Start the backend separately on the same port. Open
<http://localhost:5173>. Change `LOCAL_BACKEND_URL` whenever the backend port
changes. Use [local development](../../LOCAL_DEV_CONTAINER_DEVELOPMENT.md)
for the no-provisioning setup and its intentionally unavailable integrations.

Map credentials and capability flags are read from the backend's
`/api/config`. Without Maps credentials, Leaflet/Esri supports navigation,
zoom and pins, but not the Azure-canvas Image Analysis path. Model, Fabric and
private catalog credentials do not belong in browser source or Vite variables.

## Production Build

```powershell
$env:VITE_API_BASE_URL = 'https://<actual-api-host>'
npm run build
```

Alternatively, azd supplies `AZURE_CONTAINER_APP_URL`. An explicit
`VITE_API_BASE_URL` takes precedence. The selected origin is compiled into the
JavaScript bundle: changing App Service settings after publishing does not
rewrite it. Inspect the bundle and rebuild if it points to the wrong origin.

The build creates `dist` and adds the dependency-free Node static host.
App Service runs `node server.js`. This project uses an App Service Web App,
not Azure Static Web Apps or a Router Function App.

## Deploy or Reuse

Use the [deployment guide](../../documentation/deployment.md) for a new
environment or a named existing Web App/API. Resource name, plan and region
come from the selected environment; there is no universal pre-existing
`planetaryexplorer-web-ui` resource.

For app-only updates, verify exact names and publish `azd deploy web` from the
selected root environment, or deploy a verified `dist` ZIP to the existing
Web App. Keep authentication, runtime and plan settings unchanged unless
their modification is explicitly approved. Do not use a create-or-update
command with guessed resource names.

## Validation

```powershell
npm run test:run
npm run test:deployment
npm run build
```

For real local map and gallery checks, run the repository's
[map verifier](../../scripts/verify_map_loading.mjs) and
[gallery verifier](../../scripts/verify_get_started_gallery.mjs).
Use the release-bound [Image Analysis verifier](../../scripts/verify_get_started_image_analysis.mjs)
for deployed image workflows. Test desktop and mobile rendering, decoded
tiles, pins, correct API requests and evidence, not only successful page load.

See [Get Started](../../documentation/get-started-playbook.md) for data/date
prerequisites and interpretation limits.