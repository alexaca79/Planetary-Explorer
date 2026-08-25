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
#   Pin a region (skips preflight):
#       .\deploy-infrastructure.ps1 -Location eastus2
#
# Multi-environment support:
#       .\deploy-infrastructure.ps1                              # prod (default, rg-planetaryexplorer)
#       .\deploy-infrastructure.ps1 -EnvironmentName dev         # dev   (rg-planetaryexplorer-dev)
#
# Each environment lives in its own resource group; resource names are derived
# from the Bicep resourceToken (subscription + environmentName + location).

param(
    [Parameter(Mandatory=$false)]
    [string]$Location = "",

    [Parameter(Mandatory=$false)]
    [ValidatePattern('^[a-z0-9-]{1,40}$')]
    [string]$EnvironmentName = "planetaryexplorer",

    [Parameter(Mandatory=$false)]
    [switch]$EnableAuthentication,

    [Parameter(Mandatory=$false)]
    [string]$MicrosoftEntraClientId = "",

    [Parameter(Mandatory=$false)]
    [string]$MicrosoftEntraTenantId = "",

    [Parameter(Mandatory=$false)]
    [string]$ContainerImage = '',

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
    [bool]$DeployGeoFm = $false,

    [Parameter(Mandatory=$false)]
    [string]$GeoFmMcpApiKey = '',

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
$deployGpt5Resolved = Resolve-Bool $DeployGpt5 'DEPLOY_GPT5'
$deployGpt56Resolved = Resolve-Bool $DeployGpt56 'DEPLOY_GPT56'
$deployEmbeddingResolved = Resolve-Bool $DeployEmbeddingModel 'DEPLOY_EMBEDDING_MODEL'
$deployGeoFmResolved = Resolve-Bool $DeployGeoFm 'DEPLOY_GEOFM'

if ($deployGeoFmResolved -and $GeoFmMcpApiKey.Length -lt 32) {
    throw "GeoFmMcpApiKey must contain at least 32 characters when GeoFM is enabled."
}

if (-not $Location -and $env:LOCATION) { $Location = $env:LOCATION }

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
    if ($deployGeoFmResolved) {
        Write-Host "Validating GeoFM GPU support and quota in $Location..." -ForegroundColor Cyan
        try {
            $pinnedParams = @{} + $preflightParams
            $pinnedParams.Candidates = @($Location)
            $picked = & $selectScript @pinnedParams 2>$null
            if (-not ($picked | Where-Object { $_ -eq $Location })) {
                throw "GeoFM preflight did not approve $Location"
            }
        } catch {
            Write-Host "Pinned-region GeoFM preflight failed: $($_.Exception.Message). Aborting." -ForegroundColor Red
            exit 1
        }
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
    "location=$Location"
)
if ($ContainerImage)            { $inlineParams += "containerImage=$ContainerImage" }
if ($EnableAuthentication)      { $inlineParams += "enableAuthentication=true" }
if ($MicrosoftEntraClientId)    { $inlineParams += "microsoftEntraClientId=$MicrosoftEntraClientId" }
if ($MicrosoftEntraTenantId)    { $inlineParams += "microsoftEntraTenantId=$MicrosoftEntraTenantId" }
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
$inlineParams += "deployGeoFm=$($deployGeoFmResolved.ToString().ToLower())"
if ($GeoFmMcpApiKey) { $inlineParams += "geoFmMcpApiKey=$GeoFmMcpApiKey" }

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

$ResourceGroup = "rg-$EnvironmentName"

if ($LASTEXITCODE -eq 0) {
    Write-Host "Infrastructure deployment completed successfully!" -ForegroundColor Green

    Write-Host "`nDiscovering deployed resources..." -ForegroundColor Cyan
    $containerApp = az containerapp list --resource-group $ResourceGroup --query "[0].name" -o tsv 2>$null
    $appService   = az webapp       list --resource-group $ResourceGroup --query "[0].name" -o tsv 2>$null
    $registry     = az acr          list --resource-group $ResourceGroup --query "[0].name" -o tsv 2>$null

    Write-Host "`nDeployed Resources:" -ForegroundColor Yellow
    Write-Host "  - Resource Group    : $ResourceGroup" -ForegroundColor White
    Write-Host "  - Container App     : $containerApp"  -ForegroundColor White
    Write-Host "  - App Service       : $appService"    -ForegroundColor White
    Write-Host "  - Container Registry: $registry"      -ForegroundColor White

    Write-Host "`nInfrastructure is ready!" -ForegroundColor Green
    Write-Host "Next step: cd planetary-explorer; .\deploy-all.ps1" -ForegroundColor White
} else {
    Write-Host "Infrastructure deployment failed" -ForegroundColor Red
    Write-Host "Please check the error messages above and try again." -ForegroundColor Yellow
    exit 1
}
