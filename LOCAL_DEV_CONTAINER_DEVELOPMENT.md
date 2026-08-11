# Local dev container development

The repository includes a VS Code dev container for developing and validating
Planetary Explorer without provisioning Azure resources.

## Prerequisites

- Docker Desktop with Linux containers enabled
- Visual Studio Code
- The **Dev Containers** VS Code extension
- Access to the Microsoft corporate network when using Central Feed Service
  (CFS)
- At least 4 CPU cores, 8 GB of memory, and 32 GB of free storage

## Included tools

- Python 3.12 and an isolated virtual environment
- Node.js 20, npm, and Yarn
- Azure CLI and Bicep CLI
- Azure Developer CLI (`azd`)
- PowerShell
- Git, Git LFS, and GitHub CLI
- Docker CLI, Buildx, and Docker Compose using the host Docker daemon
- GDAL, GEOS, PROJ, and native build tools for geospatial packages
- EchoAPI for VS Code
- Recommended Python, Ruff, Prettier, ESLint, Bicep, Azure, Docker, PowerShell,
  and GitHub Actions VS Code extensions

Python 3.12 is intentional. Although Python 3.14 was considered, the project
documentation identifies Python 3.12 as the backend runtime and its native
geospatial and Azure dependencies are validated against that version.

## Open the container

1. Open the repository root in VS Code.
2. Run **Dev Containers: Reopen in Container** from the Command Palette.
3. Wait for `postCreateCommand` to finish.

The post-create process creates
`/home/vscode/.venvs/planetary-explorer`, installs the root and backend Python
requirements, and runs `npm ci` for the web UI. Re-run it when dependencies
change:

```bash
bash .devcontainer/post-create.sh
```

The Azure CLI, Azure Developer CLI, and GitHub CLI state is stored in named
Docker volumes so authentication survives container rebuilds.

## Central Feed Service

The image and package clients use these CFS endpoints:

```text
PIP_INDEX_URL=https://packagefeedproxy.microsoft.io/pypi/simple
NPM_CONFIG_REGISTRY=https://packagefeedproxy.microsoft.io/npm/
YARN_NPM_REGISTRY_SERVER=https://packagefeedproxy.microsoft.io/npm/
NUGET_CFS_SOURCE=https://packagefeedproxy.microsoft.io/nuget/v3/index.json
```

`NUGET_PACKAGES` remains a local cache path because NuGet defines that variable
as a directory, not a feed URL. The CFS NuGet URL is configured as the only
package source in `.devcontainer/NuGet.Config`.

CFS access was validated without an additional feed login. If package requests
return `401` or `403`, connect to the corporate network, complete any required
CFS sign-in described at <https://aka.ms/CFS>, and rebuild the container.

These CFS addresses are for managed local development only. Do not copy them
into deployment images or Azure runtime configuration because they are not
accessible from external deployment environments.

## Authenticate command-line tools

Authentication is not required to run the application locally. To inspect an
existing Azure subscription later, use device-code login:

```bash
az login --use-device-code
azd auth login --use-device-code
gh auth login --web
```

Authentication does not provision resources.

## Run Planetary Explorer locally

Start the backend and frontend together:

```bash
bash .devcontainer/start-local.sh
```

Open:

- Web UI: <http://localhost:5173>
- Backend configuration: <http://localhost:8000/api/config>
- Backend health: <http://localhost:8000/api/health>

The local launcher sets `DISABLE_AUTH=true` and
`RESILIENCE_FORCE_SEED=1`. It uses the bundled seed data and the public
Microsoft Planetary Computer STAC catalog. Features that need Azure OpenAI,
Azure Maps, Fabric, or private catalog configuration remain unavailable until
valid existing-service settings are supplied.

`/api/health` returns `503` with a `degraded` payload when Azure OpenAI or Azure
Maps is not configured. That is expected for the no-Azure local setup; the
backend is running if `/api/config` returns `200`.

Stop both processes with `Ctrl+C`.

## Validate without provisioning Azure

Run the repeatable validation:

```bash
bash .devcontainer/validate.sh
```

It verifies:

- Requested CLI tools and CFS client configuration
- 21 targeted backend tests
- 12 targeted frontend tests
- The production frontend build
- Bicep compilation for `planetary-explorer/infra/main.bicep`
- Live backend configuration and health responses
- A live response from the Vite web UI

It does not sign in to Azure, create an `azd` environment, submit an Azure
deployment, or provision services. `azd show` can safely confirm that the
manifest defines the `api` and `web` services:

```bash
azd show
```

Do not run `azd up`, `azd provision`, `az deployment create`, or the repository
deployment scripts when the goal is local-only development.

## Use existing Azure services

To test against services that already exist, create an untracked
`planetary-explorer/container-app/.env` file with the required endpoint,
identity, and feature settings from your environment. Never commit keys or
tokens. The application supports Azure CLI credentials through
`DefaultAzureCredential` for compatible services, so prefer `az login` over
long-lived secrets.

Local development validates that the application starts, that its Azure
infrastructure compiles, and that the `azd` service manifest loads. A complete
AI or map workflow still requires existing Azure service endpoints and
permissions; those calls were intentionally not made during dev-container
validation.

## Troubleshooting

- **Docker commands fail:** Start Docker Desktop and rebuild the container.
- **CFS packages fail:** Verify corporate network access and the four
  environment/config values above.
- **Backend health is degraded:** Expected until Azure OpenAI and Azure Maps
  are configured.
- **Port already in use:** Set `BACKEND_PORT` or `FRONTEND_PORT` before running
  `.devcontainer/start-local.sh`.
- **Dependencies changed:** Re-run `.devcontainer/post-create.sh`, then
  `.devcontainer/validate.sh`.
