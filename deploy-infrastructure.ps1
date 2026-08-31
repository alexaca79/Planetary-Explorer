# Deploy Planetary Explorer Infrastructure
# Designed for a one-command fork-and-deploy experience.
#
#   Public, all opt-ins OFF, auto-picked region (recommended for new forks):
#       .\deploy-infrastructure.ps1
#
#   Override via env vars (CI-friendly, no prompts):
#       $env:MPC_PRO='true'; $env:FABRIC='true'; .\deploy-infrastructure.ps1
#
#   Override via flags:
#       .\deploy-infrastructure.ps1 -EnableMpcPro -EnableFabric -EnablePrivateEndpoints
#
#   Pin a region (still validates required services and quota):
#       .\deploy-infrastructure.ps1 -Location eastus2
#
# Multi-environment support:
#       .\deploy-infrastructure.ps1                              # prod (default, rg-planetaryexplorer)
#       .\deploy-infrastructure.ps1 -EnvironmentName dev         # dev   (rg-planetaryexplorer-dev)
#
# Each environment lives in its own resource group; resource names are derived
# from the Bicep resourceToken (subscription + environmentName + location).

#Requires -Version 7.0

param(
    [Parameter(Mandatory=$false)]
    [string]$Location = "",

    [Parameter(Mandatory=$false)]
    [ValidatePattern('^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$')]
    [string]$EnvironmentName = "planetaryexplorer",

    [Parameter(Mandatory=$false)]
    [ValidatePattern('^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$')]
    [string]$ApiContainerAppName = '',

    [Parameter(Mandatory=$false)]
    [switch]$EnableAuthentication,

    [Parameter(Mandatory=$false)]
    [switch]$PublicDemoMode,

    [Parameter(Mandatory=$false)]
    [string]$MicrosoftEntraClientId = "",

    [Parameter(Mandatory=$false)]
    [string]$MicrosoftEntraTenantId = "",

    [Parameter(Mandatory=$false)]
    [string]$ContainerImage = '',

    [Parameter(Mandatory=$false)]
    [string]$FrontendUrl = '',

    [Parameter(Mandatory=$false)]
    [ValidatePattern('^[a-z0-9](?:[a-z0-9-]{0,58}[a-z0-9])?$')]
    [string]$FrontendWebAppName = '',

    [Parameter(Mandatory=$false)]
    [ValidatePattern('^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,38}[a-zA-Z0-9])?$')]
    [string]$FrontendAppServicePlanName = '',

    [Parameter(Mandatory=$false)]
    [switch]$DeployMcpServer,

    [Parameter(Mandatory=$false)]
    [string]$McpImageName = 'planetary-explorer-mcp:latest',

    [Parameter(Mandatory=$false)]
    [string]$McpApiKey = '',

    # Three master feature flags. Defaults are OFF so a fresh fork deploys the
    # smallest viable public stack. Each flag can also be set via env var
    # (MPC_PRO, PRIVATE, FABRIC) so CI/CD pipelines and one-click deploy
    # buttons don't need to know the PowerShell switch names.
    [Parameter(Mandatory=$false)]
    [switch]$EnableMpcPro,

    [Parameter(Mandatory=$false)]
    [switch]$EnablePrivateEndpoints,

    [Parameter(Mandatory=$false)]
    [switch]$EnableFabric,

    [Parameter(Mandatory=$false)]
    [bool]$DeployGpt5 = $false,

    [Parameter(Mandatory=$false)]
    [bool]$DeployGpt56 = $false,

    [Parameter(Mandatory=$false)]
    [bool]$DeployEmbeddingModel = $true,

    [Parameter(Mandatory=$false)]
    [string]$AgentProjectName = 'planetary-explorer-agents',

    [Parameter(Mandatory=$false)]
    [bool]$DeployGeoFm = $false,

    [Parameter(Mandatory=$false)]
    [bool]$DeployWebSearchMcp = $false,

    [Parameter(Mandatory=$false)]
    [string]$WebSearchMcpApiKey = '',

    [Parameter(Mandatory=$false)]
    [string]$GeoFmMcpApiKey = '',

    [Parameter(Mandatory=$false)]
    [string]$GeoFmOwnerSigningKey = '',

    # Forecast Agent weather models. When on, provisions the CPU-only weather
    # stub Container App and points AURORA_ENDPOINT_URL / EARTH2_FCN_ENDPOINT_URL
    # at it so the Forecast Agent works end-to-end without GPU quota. MAI
    # Weather still requires a real Foundry endpoint (provider stays inert
    # until MAI_WEATHER_ENDPOINT_URL is supplied).
    [Parameter(Mandatory=$false)]
    [switch]$EnableWeatherModels
)

# Resolve flags from env vars when switches are not supplied.
function Resolve-Flag([bool]$switchValue, [string]$envName) {
    if ($switchValue) { return $true }
    $v = [Environment]::GetEnvironmentVariable($envName)
    if ($v -and $v.ToLower() -in @('1','true','yes','on')) { return $true }
    return $false
}

function Resolve-Bool([bool]$parameterValue, [string]$envName) {
    $value = [Environment]::GetEnvironmentVariable($envName)
    if (-not $value) { return $parameterValue }
    if ($value.ToLower() -in @('1','true','yes','on')) { return $true }
    if ($value.ToLower() -in @('0','false','no','off')) { return $false }
    throw "$envName must be true or false, got '$value'."
}

$mpcPro  = Resolve-Flag $EnableMpcPro.IsPresent           'MPC_PRO'
$private = Resolve-Flag $EnablePrivateEndpoints.IsPresent 'PRIVATE'
$fabric  = Resolve-Flag $EnableFabric.IsPresent           'FABRIC'
$weather = Resolve-Flag $EnableWeatherModels.IsPresent    'WEATHER_MODELS'
$publicDemo = Resolve-Flag $PublicDemoMode.IsPresent      'PUBLIC_DEMO_MODE'
$deployGpt5Resolved = Resolve-Bool $DeployGpt5 'DEPLOY_GPT5'
$deployGpt56Resolved = Resolve-Bool $DeployGpt56 'DEPLOY_GPT56'
$deployEmbeddingResolved = Resolve-Bool $DeployEmbeddingModel 'DEPLOY_EMBEDDING_MODEL'
$deployGeoFmResolved = Resolve-Bool $DeployGeoFm 'DEPLOY_GEOFM'
$deployWebSearchResolved = Resolve-Bool $DeployWebSearchMcp 'DEPLOY_WEB_SEARCH_MCP'
if (-not $WebSearchMcpApiKey -and $env:WEB_SEARCH_MCP_API_KEY) {
    $WebSearchMcpApiKey = $env:WEB_SEARCH_MCP_API_KEY
}
if ($deployWebSearchResolved -and -not $WebSearchMcpApiKey) {
    $WebSearchMcpApiKey = [Convert]::ToBase64String(
        [System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
    )
}
if ($deployWebSearchResolved -and $WebSearchMcpApiKey.Length -lt 32) {
    throw 'WebSearchMcpApiKey must contain at least 32 characters.'
}

if (-not $GeoFmMcpApiKey -and $env:GEOFM_MCP_API_KEY) {
    $GeoFmMcpApiKey = $env:GEOFM_MCP_API_KEY
}
if (-not $GeoFmOwnerSigningKey -and $env:GEOFM_OWNER_SIGNING_KEY) {
    $GeoFmOwnerSigningKey = $env:GEOFM_OWNER_SIGNING_KEY
}

if ($deployGeoFmResolved -and $GeoFmMcpApiKey.Length -lt 32) {
    throw "GeoFmMcpApiKey must contain at least 32 characters when GeoFM is enabled."
}
if ($deployGeoFmResolved -and $GeoFmOwnerSigningKey.Length -lt 32) {
    throw "GeoFmOwnerSigningKey must contain at least 32 characters when GeoFM is enabled."
}
if (
    $deployGeoFmResolved -and
    [string]::Equals($GeoFmMcpApiKey, $GeoFmOwnerSigningKey, [StringComparison]::Ordinal)
) {
    throw "GeoFmMcpApiKey and GeoFmOwnerSigningKey must be distinct."
}

if (-not $Location -and $env:LOCATION) { $Location = $env:LOCATION }
if (-not $FrontendUrl -and $env:FRONTEND_URL) { $FrontendUrl = $env:FRONTEND_URL }
if ($FrontendUrl) {
    $parsedFrontend = $null
    if (
        -not [Uri]::TryCreate($FrontendUrl, [UriKind]::Absolute, [ref]$parsedFrontend) -or
        $parsedFrontend.Scheme -ne 'https' -or
        -not $parsedFrontend.Host
    ) {
        throw "FrontendUrl must be an absolute HTTPS origin."
    }
}

Write-Host "Planetary Explorer Infrastructure Deployment" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host "Environment   : $EnvironmentName"            -ForegroundColor Cyan
Write-Host "Resource Group: rg-$EnvironmentName"          -ForegroundColor Cyan
Write-Host "Flags         : MpcPro=$mpcPro  Private=$private  Fabric=$fabric  WeatherModels=$weather" -ForegroundColor Cyan
Write-Host "Models        : GPT5=$deployGpt5Resolved  GPT56=$deployGpt56Resolved  Embeddings=$deployEmbeddingResolved  GeoFM=$deployGeoFmResolved" -ForegroundColor Cyan

$deploymentName = "planetary-explorer-$EnvironmentName-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Check if already signed in to Azure
Write-Host "`nChecking Azure authentication..." -ForegroundColor Cyan
az account show 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Please sign in to Azure..." -ForegroundColor Yellow
    az login | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to sign in to Azure" -ForegroundColor Red
        exit 1
    }
}
Write-Host "Authenticated with Azure" -ForegroundColor Green

$ResourceGroup = "rg-$EnvironmentName"
$targetResolver = Join-Path $PSScriptRoot 'scripts/resolve_deployment_targets.py'
$resolverArgs = @(
    $targetResolver,
    '--resource-group', $ResourceGroup,
    '--environment-name', $EnvironmentName
)
if ($ApiContainerAppName) { $resolverArgs += @('--api-name', $ApiContainerAppName) }
if ($FrontendWebAppName) { $resolverArgs += @('--web-name', $FrontendWebAppName) }
if ($FrontendAppServicePlanName) {
    $resolverArgs += @('--plan-name', $FrontendAppServicePlanName)
}
if ($FrontendUrl) { $resolverArgs += @('--frontend-url', $FrontendUrl) }
$resolvedTargetsJson = & python @resolverArgs
if ($LASTEXITCODE -ne 0) {
    throw 'Existing deployment target resolution failed.'
}
$resolvedTargets = $resolvedTargetsJson | ConvertFrom-Json
if (-not $ApiContainerAppName) {
    $ApiContainerAppName = $resolvedTargets.api_container_app_name
}
if (-not $FrontendWebAppName) {
    $FrontendWebAppName = $resolvedTargets.frontend_web_app_name
}
if (-not $FrontendAppServicePlanName) {
    $FrontendAppServicePlanName = $resolvedTargets.frontend_app_service_plan_name
}
if (-not $FrontendUrl) {
    $FrontendUrl = $resolvedTargets.frontend_url
}
$existingApiUrl = $resolvedTargets.api_container_app_url
$existingContainerAppsEnvironmentName = $resolvedTargets.container_apps_environment_name
$deployApiContainerResolved = [bool]$resolvedTargets.deploy_api_container
if ($PSBoundParameters.ContainsKey('ContainerImage') -and $ContainerImage) {
    $deployApiContainerResolved = $true
}
if ($deployApiContainerResolved -and -not $ContainerImage) {
    $ContainerImage = 'mcr.microsoft.com/k8se/quickstart:latest'
}
$deployFrontendResolved = [bool]$resolvedTargets.deploy_frontend
if ($deployApiContainerResolved) {
    if ($EnableAuthentication.IsPresent -eq $publicDemo) {
        throw 'Fresh deployments require exactly one of -EnableAuthentication or -PublicDemoMode.'
    }
    if (
        $EnableAuthentication.IsPresent -and
        (-not $MicrosoftEntraClientId -or -not $MicrosoftEntraTenantId)
    ) {
        throw 'EnableAuthentication requires MicrosoftEntraClientId and MicrosoftEntraTenantId.'
    }
}

# ========================================
# AUTO-SELECT REGION (preflight)
# ========================================
$selectScript = Join-Path $PSScriptRoot 'planetary-explorer/scripts/select-region.ps1'
$preflightParams = @{
    DeployGpt5 = $deployGpt5Resolved
    DeployGpt56 = $deployGpt56Resolved
    DeployEmbeddingModel = $deployEmbeddingResolved
    DeployGeoFm = $deployGeoFmResolved
    EnableMpcPro = $mpcPro
    EnablePrivateEndpoints = $private
    EnableFabric = $fabric
}
if (-not (Test-Path $selectScript)) {
    Write-Host "Preflight script not found at $selectScript. Aborting." -ForegroundColor Red
    exit 1
}

if (-not $Location) {
    Write-Host "`nNo -Location supplied. Running region preflight..." -ForegroundColor Cyan
    try {
        $picked = & $selectScript @preflightParams 2>$null
        if ($picked) {
            $Location = ($picked | Where-Object { $_ -and $_ -match '^[a-z][a-z0-9]+$' } | Select-Object -Last 1)
        }
        if (-not $Location) { throw "preflight returned empty region" }
        Write-Host "Auto-selected region: $Location" -ForegroundColor Green
    } catch {
        Write-Host "Region preflight failed: $($_.Exception.Message). Aborting." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "Using pinned region: $Location" -ForegroundColor Green
    Write-Host "Validating required services and quota in $Location..." -ForegroundColor Cyan
    try {
        $pinnedParams = @{} + $preflightParams
        $pinnedParams.Candidates = @($Location)
        $picked = & $selectScript @pinnedParams 2>$null
        if (-not ($picked | Where-Object { $_ -eq $Location })) {
            throw "Region preflight did not approve $Location"
        }
    } catch {
        Write-Host "Pinned-region preflight failed: $($_.Exception.Message). Aborting." -ForegroundColor Red
        exit 1
    }
}

Write-Host "`nDeployment Configuration:" -ForegroundColor Yellow
Write-Host "Location       : $Location"        -ForegroundColor White
Write-Host "Deployment Name: $deploymentName"  -ForegroundColor White
Write-Host "Note: main.bicep is subscription-scoped and will create resource group 'rg-$EnvironmentName' automatically." -ForegroundColor Gray

# Build inline parameter overrides. These take precedence over main.parameters.json
# so the same parameters file can serve prod + dev + any future env.
$inlineParams = @(
    "environmentName=$EnvironmentName",
    "location=$Location",
    "containerImage=$ContainerImage",
    "apiContainerAppName=$ApiContainerAppName",
    "existingContainerAppsEnvironmentName=$existingContainerAppsEnvironmentName",
    "existingApiUrl=$existingApiUrl",
    "frontendUrl=$FrontendUrl",
    "frontendWebAppName=$FrontendWebAppName",
    "frontendAppServicePlanName=$FrontendAppServicePlanName",
    "microsoftEntraClientId=$MicrosoftEntraClientId",
    "microsoftEntraTenantId=$MicrosoftEntraTenantId"
)
$inlineParams += "deployApiContainer=$($deployApiContainerResolved.ToString().ToLower())"
$inlineParams += "deployFrontend=$($deployFrontendResolved.ToString().ToLower())"
$inlineParams += "enableAuthentication=$($EnableAuthentication.IsPresent.ToString().ToLower())"
$inlineParams += "publicDemoMode=$($publicDemo.ToString().ToLower())"
if ($DeployMcpServer) {
    $inlineParams += "deployMcpServer=true"
    $inlineParams += "mcpImageName=$McpImageName"
    if ($McpApiKey) { $inlineParams += "mcpApiKey=$McpApiKey" }
}

# Master feature toggles (always emitted so explicit OFF wins over any stale parameters file).
$inlineParams += "enableMpcPro=$($mpcPro.ToString().ToLower())"
$inlineParams += "enablePrivateEndpoints=$($private.ToString().ToLower())"
$inlineParams += "enableFabric=$($fabric.ToString().ToLower())"
$inlineParams += "deployWeatherStub=$($weather.ToString().ToLower())"
$inlineParams += "deployGpt5=$($deployGpt5Resolved.ToString().ToLower())"
$inlineParams += "deployGpt56=$($deployGpt56Resolved.ToString().ToLower())"
$inlineParams += "deployEmbeddingModel=$($deployEmbeddingResolved.ToString().ToLower())"
$inlineParams += "agentProjectName=$AgentProjectName"
$inlineParams += "deployGeoFm=$($deployGeoFmResolved.ToString().ToLower())"
$inlineParams += "deployGeoFmServices=$($deployGeoFmResolved.ToString().ToLower())"
$inlineParams += "deployWebSearchMcp=$($deployWebSearchResolved.ToString().ToLower())"
$inlineParams += "webSearchMcpApiKey=$WebSearchMcpApiKey"
$inlineParams += "geoFmMcpApiKey=$GeoFmMcpApiKey"
$inlineParams += "geoFmOwnerSigningKey=$GeoFmOwnerSigningKey"

# Validate before deploying - surfaces region/SKU/quota issues without partial provisioning.
Write-Host "`nValidating template..." -ForegroundColor Cyan
az deployment sub validate `
    --location $Location `
    --template-file "planetary-explorer/infra/main.bicep" `
    --parameters "planetary-explorer/infra/main.parameters.json" `
    --parameters $inlineParams `
    --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Template validation failed. Aborting before deployment." -ForegroundColor Red
    exit 1
}
Write-Host "Validation passed." -ForegroundColor Green

# Deploy the infrastructure (subscription-scoped).
Write-Host "`nDeploying infrastructure..." -ForegroundColor Cyan
Write-Host "This may take several minutes..." -ForegroundColor Yellow

az deployment sub create `
    --location $Location `
    --template-file "planetary-explorer/infra/main.bicep" `
    --parameters "planetary-explorer/infra/main.parameters.json" `
    --parameters $inlineParams `
    --name $deploymentName

if ($LASTEXITCODE -eq 0) {
    Write-Host "Infrastructure deployment completed successfully!" -ForegroundColor Green

    Write-Host "`nDiscovering deployed resources..." -ForegroundColor Cyan
    $deploymentOutputs = az deployment sub show --name $deploymentName `
        --query properties.outputs -o json | ConvertFrom-Json
    $containerApp = $deploymentOutputs.AZURE_CONTAINER_APP_NAME.value
    $registry = $deploymentOutputs.AZURE_CONTAINER_REGISTRY_NAME.value
    $appService = $deploymentOutputs.AZURE_WEB_APP_NAME.value
    if ($containerApp -and (
        -not $deployApiContainerResolved -or
        $ContainerImage -ne 'mcr.microsoft.com/k8se/quickstart:latest'
    )) {
        $env:AZURE_COSMOS_CHAT_HISTORY_ENDPOINT = $deploymentOutputs.AZURE_COSMOS_CHAT_HISTORY_ENDPOINT.value
        $env:AZURE_COSMOS_CHAT_HISTORY_DATABASE = $deploymentOutputs.AZURE_COSMOS_CHAT_HISTORY_DATABASE.value
        $env:AZURE_COSMOS_CHAT_HISTORY_CONTAINER = $deploymentOutputs.AZURE_COSMOS_CHAT_HISTORY_CONTAINER.value
        $env:AZURE_CHAT_ARTIFACT_BLOB_ENDPOINT = $deploymentOutputs.AZURE_CHAT_ARTIFACT_BLOB_ENDPOINT.value
        $env:AZURE_CHAT_ARTIFACT_CONTAINER = $deploymentOutputs.AZURE_CHAT_ARTIFACT_CONTAINER.value
        $env:AZURE_WEB_SEARCH_MCP_URL = $deploymentOutputs.AZURE_WEB_SEARCH_MCP_URL.value
        $env:WEB_SEARCH_MCP_API_KEY = $WebSearchMcpApiKey
        $env:AZURE_WEATHER_STUB_URL = $deploymentOutputs.AZURE_WEATHER_STUB_URL.value
        $env:AZURE_GEOFM_MCP_URL = $deploymentOutputs.AZURE_GEOFM_MCP_URL.value
        $env:GEOFM_MCP_API_KEY = $GeoFmMcpApiKey
        $env:GEOFM_OWNER_SIGNING_KEY = $GeoFmOwnerSigningKey
        $env:PUBLIC_DEMO_MODE = $publicDemo.ToString().ToLower()
        $apiPostDeploy = Join-Path $PSScriptRoot 'scripts/configure_api_postdeploy.py'
        python $apiPostDeploy --profile api --name $containerApp `
            --resource-group $ResourceGroup
        if ($LASTEXITCODE -ne 0) { throw 'API optional-service reconciliation failed.' }
    }
    if (-not $appService -and $FrontendUrl) {
        $frontendHost = ([Uri]$FrontendUrl).Host
        if ($frontendHost.EndsWith('.azurewebsites.net')) {
            $candidateAppService = $frontendHost.Substring(
                0,
                $frontendHost.Length - '.azurewebsites.net'.Length
            )
            az webapp show --resource-group $ResourceGroup --name $candidateAppService `
                --output none 2>$null
            if ($LASTEXITCODE -eq 0) {
                $appService = $candidateAppService
            }
        }
    }

    if ($deployGeoFmResolved) {
        Write-Host "`nPublishing GeoFM control-plane and worker images..." -ForegroundColor Cyan
        $geoFmMcpApp = az deployment sub show --name $deploymentName `
            --query "properties.outputs.AZURE_GEOFM_MCP_CONTAINER_APP_NAME.value" -o tsv
        $geoFmWorkerApp = az deployment sub show --name $deploymentName `
            --query "properties.outputs.AZURE_GEOFM_WORKER_CONTAINER_APP_NAME.value" -o tsv
        if (-not $registry -or -not $geoFmMcpApp -or -not $geoFmWorkerApp) {
            throw "GeoFM deployment outputs are incomplete; refusing to leave bootstrap images active."
        }

        $imageTag = Get-Date -Format "yyyyMMddHHmmss"
        $geoFmRoot = Join-Path $PSScriptRoot "planetary-explorer/geofm-sidecar"
        $agentPool = az acr agentpool list --registry $registry `
            --query "[?count > ``0``].name | [0]" -o tsv 2>$null

        $buildCommon = @("acr", "build", "--registry", $registry, "--timeout", "3600")
        if ($agentPool) {
            $buildCommon += @("--agent-pool", $agentPool)
        }

        $mcpImage = "planetary-explorer-geofm-mcp:$imageTag"
        $mcpBuild = $buildCommon + @(
            "--image", $mcpImage,
            "--file", (Join-Path $geoFmRoot "Dockerfile"),
            $geoFmRoot
        )
        & az @mcpBuild
        if ($LASTEXITCODE -ne 0) { throw "GeoFM MCP image build failed." }

        $workerImage = "planetary-explorer-geofm-worker:$imageTag"
        $workerBuild = $buildCommon + @(
            "--image", $workerImage,
            "--file", (Join-Path $geoFmRoot "Dockerfile.worker"),
            $geoFmRoot
        )
        & az @workerBuild
        if ($LASTEXITCODE -ne 0) { throw "GeoFM worker image build failed." }

        $registryServer = az acr show --name $registry --resource-group $ResourceGroup `
            --query loginServer -o tsv
        az containerapp update --name $geoFmMcpApp --resource-group $ResourceGroup `
            --image "$registryServer/$mcpImage" --output none
        if ($LASTEXITCODE -ne 0) { throw "GeoFM MCP image update failed." }
        $postDeployScript = Join-Path $PSScriptRoot 'scripts/configure_api_postdeploy.py'
        python $postDeployScript --profile geofm --name $geoFmMcpApp `
            --resource-group $ResourceGroup
        if ($LASTEXITCODE -ne 0) { throw "GeoFM MCP probe configuration failed." }
        az containerapp update --name $geoFmWorkerApp --resource-group $ResourceGroup `
            --image "$registryServer/$workerImage" --output none
        if ($LASTEXITCODE -ne 0) { throw "GeoFM worker image update failed." }

        $mcpRevision = az containerapp show --name $geoFmMcpApp --resource-group $ResourceGroup `
            --query properties.latestRevisionName -o tsv
        $deployedWorkerImage = az containerapp show --name $geoFmWorkerApp `
            --resource-group $ResourceGroup `
            --query properties.template.containers[0].image -o tsv
        $workerMinReplicas = az containerapp show --name $geoFmWorkerApp `
            --resource-group $ResourceGroup --query properties.template.scale.minReplicas -o tsv
        $readyCommand = 'python -c "import urllib.request; urllib.request.urlopen(''http://localhost:8080/ready'', timeout=10).read()"'
        $mcpReady = $false
        foreach ($attempt in 1..40) {
            $mcpHealth = az containerapp revision show --name $geoFmMcpApp `
                --resource-group $ResourceGroup --revision $mcpRevision `
                --query properties.healthState -o tsv
            if ($mcpHealth -eq 'Healthy') {
                az containerapp exec --name $geoFmMcpApp --resource-group $ResourceGroup `
                    --revision $mcpRevision --command $readyCommand | Out-Null
                if ($LASTEXITCODE -eq 0) {
                    $mcpReady = $true
                    break
                }
            }
            if ($attempt -lt 40) {
                Start-Sleep -Seconds 15
            }
        }
        if (-not $mcpReady) {
            throw "GeoFM MCP dependency readiness check failed."
        }
        if ($deployedWorkerImage -ne "$registryServer/$workerImage" -or $workerMinReplicas -ne "0") {
            throw "GeoFM worker image or scale-to-zero verification failed."
        }
        if ($containerApp) {
            $geoFmMcpUrl = az deployment sub show --name $deploymentName `
                --query "properties.outputs.AZURE_GEOFM_MCP_URL.value" -o tsv
            az containerapp secret set --name $containerApp --resource-group $ResourceGroup `
                --secrets `
                    "geofm-mcp-api-key=$GeoFmMcpApiKey" `
                    "geofm-owner-signing-key=$GeoFmOwnerSigningKey" `
                --output none
            if ($LASTEXITCODE -ne 0) { throw 'GeoFM API secret reconciliation failed.' }
            az containerapp update --name $containerApp --resource-group $ResourceGroup `
                --set-env-vars `
                    "GEOFM_ENABLED=true" `
                    "GEOFM_MCP_URL=$geoFmMcpUrl" `
                    "GEOFM_MCP_API_KEY=secretref:geofm-mcp-api-key" `
                    "GEOFM_OWNER_SIGNING_KEY=secretref:geofm-owner-signing-key" `
                --output none
            if ($LASTEXITCODE -ne 0) { throw 'GeoFM API endpoint reconciliation failed.' }
        }
        Write-Host "GeoFM images published and verified." -ForegroundColor Green
    }

    if ($deployWebSearchResolved) {
        Write-Host "`nPublishing Azure Web Search MCP image..." -ForegroundColor Cyan
        $webSearchApp = az deployment sub show --name $deploymentName `
            --query "properties.outputs.AZURE_WEB_SEARCH_MCP_CONTAINER_APP_NAME.value" -o tsv
        if (-not $registry -or -not $webSearchApp) {
            throw "Web Search MCP deployment outputs are incomplete."
        }
        $imageTag = Get-Date -Format "yyyyMMddHHmmss"
        $webSearchRoot = Join-Path $PSScriptRoot "planetary-explorer/web-search-mcp"
        $webSearchImage = "planetary-explorer-web-search-mcp:$imageTag"
        $buildRegistry = $registry
        $temporaryBuildRegistry = ''
        $agentPool = az acr agentpool list --registry $registry `
            --query "[?count > ``0``].name | [0]" -o tsv 2>$null
        $registryPna = az acr show --name $registry --resource-group $ResourceGroup `
            --query publicNetworkAccess -o tsv
        $registryDefaultAction = az acr show --name $registry --resource-group $ResourceGroup `
            --query networkRuleSet.defaultAction -o tsv
        if (-not $agentPool -and (
            $registryPna -eq 'Disabled' -or $registryDefaultAction -eq 'Deny'
        )) {
            $temporaryBuildRegistry = 'crbuild' + [guid]::NewGuid().ToString('N').Substring(0, 16)
            az acr create --name $temporaryBuildRegistry --resource-group $ResourceGroup `
                --location $Location --sku Basic --admin-enabled false `
                --public-network-enabled true --output none
            if ($LASTEXITCODE -ne 0) { throw 'Temporary Web Search build ACR creation failed.' }
            $buildRegistry = $temporaryBuildRegistry
        }
        try {
            $webSearchBuild = @(
                'acr', 'build',
                '--registry', $buildRegistry,
                '--image', $webSearchImage,
                '--file', (Join-Path $webSearchRoot 'Dockerfile'),
                $webSearchRoot,
                '--platform', 'linux/amd64'
            )
            if ($agentPool) { $webSearchBuild += @('--agent-pool', $agentPool) }
            & az @webSearchBuild
            if ($LASTEXITCODE -ne 0) { throw "Web Search MCP image build failed." }
            if ($buildRegistry -ne $registry) {
                $buildRegistryId = az acr show --name $buildRegistry `
                    --resource-group $ResourceGroup --query id -o tsv
                az acr import --name $registry --resource-group $ResourceGroup `
                    --registry $buildRegistryId --source $webSearchImage `
                    --image $webSearchImage --force
                if ($LASTEXITCODE -ne 0) { throw 'Web Search image import failed.' }
            }
        }
        finally {
            if ($temporaryBuildRegistry) {
                az acr delete --name $temporaryBuildRegistry `
                    --resource-group $ResourceGroup --yes --output none
            }
        }
        $registryServer = az acr show --name $registry --resource-group $ResourceGroup `
            --query loginServer -o tsv
        az containerapp registry set --name $webSearchApp `
            --resource-group $ResourceGroup --server $registryServer `
            --identity system --output none
        if ($LASTEXITCODE -ne 0) { throw "Web Search MCP registry binding failed." }
        az containerapp update --name $webSearchApp --resource-group $ResourceGroup `
            --image "$registryServer/$webSearchImage" --output none
        if ($LASTEXITCODE -ne 0) { throw "Web Search MCP image update failed." }
        $postDeployScript = Join-Path $PSScriptRoot 'scripts/configure_api_postdeploy.py'
        python $postDeployScript --profile web-search --name $webSearchApp `
            --resource-group $ResourceGroup
        if ($LASTEXITCODE -ne 0) { throw "Web Search MCP probe configuration failed." }
        if ($containerApp) {
            $webSearchUrl = az deployment sub show --name $deploymentName `
                --query "properties.outputs.AZURE_WEB_SEARCH_MCP_URL.value" -o tsv
            az containerapp update --name $containerApp --resource-group $ResourceGroup `
                --set-env-vars `
                    "WEB_SEARCH_ENABLED=true" `
                    "WEB_SEARCH_MCP_URL=$webSearchUrl" `
                --output none
            if ($LASTEXITCODE -ne 0) { throw "Web Search API endpoint reconciliation failed." }
        }
        Write-Host "Web Search MCP image published and verified." -ForegroundColor Green
    }

    Write-Host "`nDeployed Resources:" -ForegroundColor Yellow
    Write-Host "  - Resource Group    : $ResourceGroup" -ForegroundColor White
    Write-Host "  - Container App     : $containerApp"  -ForegroundColor White
    Write-Host "  - App Service       : $appService"    -ForegroundColor White
    Write-Host "  - Container Registry: $registry"      -ForegroundColor White

    Write-Host "`nInfrastructure is ready!" -ForegroundColor Green
    if ($containerApp) {
        Write-Host "Next step: cd planetary-explorer; .\deploy-all.ps1 -ContainerAppName $containerApp" -ForegroundColor White
    } else {
        Write-Host "No API Container App exists yet. Build an API image and rerun with -ContainerImage before deploy-all.ps1." -ForegroundColor Yellow
    }
} else {
    Write-Host "Infrastructure deployment failed" -ForegroundColor Red
    Write-Host "Please check the error messages above and try again." -ForegroundColor Yellow
    exit 1
}
