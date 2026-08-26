# Planetary Explorer Backend Deployment Script
# Deploys the Container App (backend API) to Azure
# Auto-discovers resources from Azure subscription

param(
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroup = "",
    
    [Parameter(Mandatory=$false)]
    [string]$ContainerAppName = "",

    [Parameter(Mandatory=$false)]
    [string]$AppServiceName = "",
    
    [Parameter(Mandatory=$false)]
    [string]$Registry = "",
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipBuild = $false,
    
    [Parameter(Mandatory=$false)]
    [switch]$ShowDetails = $false
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "PLANETARY EXPLORER BACKEND DEPLOYMENT" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Get script directory (container-app folder)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir  # planetary-explorer folder
$RepoRoot = Split-Path -Parent $ProjectRoot   # repository root

Write-Host "[Directories]" -ForegroundColor Yellow
Write-Host "   Script:  $ScriptDir" -ForegroundColor Gray
Write-Host "   Project: $ProjectRoot" -ForegroundColor Gray
Write-Host "   Repo:    $RepoRoot" -ForegroundColor Gray
Write-Host ""

# Check Azure CLI
Write-Host "[Checking Azure CLI]" -ForegroundColor Cyan
try {
    $azVersion = az version --output json | ConvertFrom-Json
    Write-Host "[OK] Azure CLI version: $($azVersion.'azure-cli')" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Azure CLI not found. Please install from https://aka.ms/installazurecliwindows" -ForegroundColor Red
    exit 1
}

# Check if logged in to Azure
Write-Host "[Checking Azure login]" -ForegroundColor Cyan
try {
    $account = az account show 2>$null | ConvertFrom-Json
    Write-Host "[OK] Logged in as: $($account.user.name)" -ForegroundColor Green
    Write-Host "   Subscription: $($account.name)" -ForegroundColor Gray
} catch {
    Write-Host "[ERROR] Not logged in to Azure. Running 'az login'..." -ForegroundColor Yellow
    az login
}

# ========================================
# AUTO-DISCOVER RESOURCES IF NOT PROVIDED
# ========================================
Write-Host ""
Write-Host "[Discovering Azure Resources]" -ForegroundColor Cyan

# Find resource group if not provided
if ([string]::IsNullOrEmpty($ResourceGroup)) {
    Write-Host "   Looking for Planetary Explorer resource group..." -ForegroundColor Gray
    
    # Try to find resource group with planetaryexplorer in the name
    $groups = az group list --query "[?contains(name, 'planetaryexplorer') || contains(name, 'planetary-explorer')].name" -o tsv 2>$null
    
    $groupMatches = @($groups -split "`n" | Where-Object { $_.Trim() })
    if ($groupMatches.Count -eq 1) {
        $ResourceGroup = $groupMatches[0].Trim()
        Write-Host "[OK] Found resource group: $ResourceGroup" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] Expected exactly one Planetary Explorer resource group, found $($groupMatches.Count)." -ForegroundColor Red
        Write-Host "   Please specify -ResourceGroup parameter or create infrastructure first." -ForegroundColor Yellow
        exit 1
    }
} else {
    Write-Host "[OK] Using provided resource group: $ResourceGroup" -ForegroundColor Green
}

# Find Container App if not provided
if ([string]::IsNullOrEmpty($ContainerAppName)) {
    Write-Host "   Looking for Container App in $ResourceGroup..." -ForegroundColor Gray
    
    $canonicalApiName = if ($ResourceGroup.StartsWith('rg-')) {
        "ca-$($ResourceGroup.Substring(3))-api"
    } else {
        ''
    }
    if ($canonicalApiName) {
        az containerapp show --resource-group $ResourceGroup --name $canonicalApiName `
            --output none 2>$null
        if ($LASTEXITCODE -eq 0) {
            $ContainerAppName = $canonicalApiName
        }
    }
    if (-not $ContainerAppName) {
        $containerApps = @(az containerapp list --resource-group $ResourceGroup `
            --output json 2>$null | ConvertFrom-Json)
        $matches = @(
            $containerApps | Where-Object {
                $_.tags.'azd-service-name' -in @('api', 'web') -or
                $_.name -like 'ca-web-*'
            }
        )
        if ($matches.Count -eq 1) {
            $ContainerAppName = $matches[0].name
        }
    }
    if ($ContainerAppName) {
        Write-Host "[OK] Found API Container App: $ContainerAppName" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] Could not find Container App in resource group '$ResourceGroup'." -ForegroundColor Red
        Write-Host "   Pass -ContainerAppName or tag exactly one app with azd-service-name=api." -ForegroundColor Yellow
        exit 1
    }
} else {
    Write-Host "[OK] Using provided Container App: $ContainerAppName" -ForegroundColor Green
}

# Find Container Registry if not provided
if ([string]::IsNullOrEmpty($Registry)) {
    Write-Host "   Looking for Container Registry in $ResourceGroup..." -ForegroundColor Gray
    
    $registries = az acr list --resource-group $ResourceGroup --query "[].name" -o tsv 2>$null
    
    if ($registries) {
        $Registry = ($registries -split "`n")[0].Trim()
        Write-Host "[OK] Found Container Registry: $Registry" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] Could not find Container Registry in resource group '$ResourceGroup'." -ForegroundColor Red
        Write-Host "   Please specify -Registry parameter or deploy infrastructure first." -ForegroundColor Yellow
        exit 1
    }
} else {
    Write-Host "[OK] Using provided Container Registry: $Registry" -ForegroundColor Green
}

if (-not $SkipBuild) {
    # Build and push Docker image
    Write-Host ""
    Write-Host "[Building Docker image]" -ForegroundColor Cyan
    Write-Host "   Registry: $Registry.azurecr.io" -ForegroundColor Gray
    Write-Host "   Image: planetaryexplorer-api" -ForegroundColor Gray
    Write-Host ""
    
    $timestamp = Get-Date -Format "yyyyMMddHHmmss"
    $imageTag = $timestamp
    
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "STEP 1/3: BUILDING DOCKER IMAGE IN AZURE" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "[Building image with tag: $imageTag]" -ForegroundColor Yellow
    Write-Host "[NOTE] This will take 3-5 minutes. Progress updates every 15 seconds..." -ForegroundColor Yellow
    Write-Host ""
    
    # Change to repository root for correct build context
    Push-Location $RepoRoot
    
    try {
        # Start build with --no-wait to avoid interactive prompts
        Write-Host "[Starting ACR build...]" -ForegroundColor Cyan
        az acr build `
            --registry $Registry `
            --image "planetaryexplorer-api:$imageTag" `
            --image "planetaryexplorer-api:latest" `
            --file "planetary-explorer/container-app/Dockerfile.complete" `
            --no-wait `
            planetary-explorer/
        
        if ($LASTEXITCODE -ne 0) {
            throw "ACR build start failed"
        }
        
        Write-Host "[OK] Build started in Azure Container Registry" -ForegroundColor Green
        Write-Host ""
        
        # Poll for completion
        Write-Host "[Monitoring build progress...]" -ForegroundColor Cyan
        $maxWaitSeconds = 600  # 10 minutes max
        $elapsedSeconds = 0
        $buildComplete = $false
        
        while ($elapsedSeconds -lt $maxWaitSeconds) {
            Start-Sleep -Seconds 15
            $elapsedSeconds += 15
            
            # Get latest build run
            $runs = az acr task list-runs --registry $Registry --top 1 --output json | ConvertFrom-Json
            $latestRun = $runs[0]
            
            $status = $latestRun.status
            $runId = $latestRun.runId
            
            $minutes = [math]::Floor($elapsedSeconds / 60)
            $seconds = $elapsedSeconds % 60
            
            if ($status -eq "Succeeded") {
                Write-Host "[OK] Build completed successfully! (Run: $runId, Time: ${minutes}m ${seconds}s)" -ForegroundColor Green
                $buildComplete = $true
                break
            } elseif ($status -eq "Failed") {
                throw "Build failed (Run: $runId)"
            } elseif ($status -eq "Running") {
                Write-Host "[${minutes}m ${seconds}s] Build in progress... (Run: $runId)" -ForegroundColor Yellow
            } else {
                Write-Host "[${minutes}m ${seconds}s] Build status: $status (Run: $runId)" -ForegroundColor Gray
            }
        }
        
        if (-not $buildComplete) {
            throw "Build timed out after $maxWaitSeconds seconds"
        }
        
        Write-Host ""
        
    } catch {
        Write-Host "[ERROR] Build failed: $_" -ForegroundColor Red
        Pop-Location
        exit 1
    } finally {
        Pop-Location
    }
} else {
    Write-Host ""
    Write-Host "[SKIP] Skipping build (using existing latest tag)" -ForegroundColor Yellow
    $imageTag = "latest"
}

# Deploy to Container App
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "STEP 2/3: DEPLOYING TO CONTAINER APP" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   Resource Group: $ResourceGroup" -ForegroundColor Gray
Write-Host "   Container App: $ContainerAppName" -ForegroundColor Gray
Write-Host "   Image Tag: $imageTag" -ForegroundColor Gray
Write-Host ""

# ======================================================================
# CRITICAL FIX: Save environment variables BEFORE updating the image
# Azure Container Apps resets env vars when updating the image directly
# ======================================================================
Write-Host "[Saving current environment variables...]" -ForegroundColor Yellow
$currentEnvJson = az containerapp show `
    --name $ContainerAppName `
    --resource-group $ResourceGroup `
    --query "properties.template.containers[0].env" `
    -o json 2>$null

$currentEnv = @{}
if ($currentEnvJson) {
    $envArray = $currentEnvJson | ConvertFrom-Json
    foreach ($env in $envArray) {
        if ($null -ne $env.value) {
            $currentEnv[$env.name] = $env.value
        } elseif ($env.secretRef) {
            $currentEnv[$env.name] = "secretref:$($env.secretRef)"
        }
    }
}

# Extract critical values with defaults
$azureOpenAiEndpoint = if ($currentEnv["AZURE_OPENAI_ENDPOINT"]) { $currentEnv["AZURE_OPENAI_ENDPOINT"] } else { "" }
$useManagedIdentity = if ($currentEnv["USE_MANAGED_IDENTITY"] -eq "true") { "true" } else { "true" }

Write-Host "   AZURE_OPENAI_ENDPOINT: $azureOpenAiEndpoint" -ForegroundColor Gray
Write-Host "   USE_MANAGED_IDENTITY: $useManagedIdentity" -ForegroundColor Gray
Write-Host ""

try {
    # ======================================================================
    # CRITICAL FIX: Update image AND env vars in ONE atomic operation
    # This prevents 503 errors from race condition between image update
    # and env var restoration. Azure creates a single new revision with both.
    # ======================================================================
    Write-Host "[Updating Container App with image AND environment variables (atomic)]" -ForegroundColor Cyan
    
    $currentEnv["PORT"] = if ($currentEnv["PORT"]) { $currentEnv["PORT"] } else { "8080" }
    $currentEnv["STAC_API_URL"] = if ($currentEnv["STAC_API_URL"]) { $currentEnv["STAC_API_URL"] } else { "https://planetarycomputer.microsoft.com/api/stac/v1" }
    $corsOrigins = $currentEnv["CORS_ORIGINS"]
    $corsTokens = @(
        $corsOrigins -split ',' |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ }
    )
    if (-not $corsOrigins -or $corsTokens -contains '*') {
        if (-not $AppServiceName) {
            $appServices = @(az webapp list --resource-group $ResourceGroup `
                --output json 2>$null | ConvertFrom-Json)
            $frontendApps = @(
                $appServices | Where-Object {
                    $_.tags.'azd-service-name' -eq 'web'
                }
            )
            if ($frontendApps.Count -ne 1) {
                throw "CORS_ORIGINS requires an exact frontend, but $($frontendApps.Count) Web Apps are tagged azd-service-name=web. Pass -AppServiceName."
            }
            $AppServiceName = $frontendApps[0].name
        }
        $webHost = az webapp show --resource-group $ResourceGroup `
            --name $AppServiceName --query defaultHostName -o tsv 2>$null
        if (-not $webHost) {
            throw "CORS_ORIGINS is unsafe and frontend Web App '$AppServiceName' was not found."
        }
        $corsOrigins = "https://$($webHost.Trim()),http://localhost:5173"
    }
    $currentEnv["CORS_ORIGINS"] = $corsOrigins
    $currentEnv["AZURE_OPENAI_ENDPOINT"] = $azureOpenAiEndpoint
    $currentEnv["USE_MANAGED_IDENTITY"] = $useManagedIdentity
    $envVars = @(
        $currentEnv.GetEnumerator() |
            Sort-Object -Property Name |
            ForEach-Object { "$($_.Key)=$($_.Value)" }
    )
    
    # Single atomic update: image + all env vars together
    az containerapp update `
        --name $ContainerAppName `
        --resource-group $ResourceGroup `
        --image "$Registry.azurecr.io/planetaryexplorer-api:$imageTag" `
        --set-env-vars @envVars `
        --output none
    
    if ($LASTEXITCODE -ne 0) {
        throw "Container App update failed"
    }

    Write-Host "[Setting API ingress target port to 8080]" -ForegroundColor Cyan
    az containerapp ingress update `
        --name $ContainerAppName `
        --resource-group $ResourceGroup `
        --target-port 8080 `
        --output none

    if ($LASTEXITCODE -ne 0) {
        throw "Container App ingress update failed"
    }

    Write-Host "[Enabling sticky sessions for conversation continuity]" -ForegroundColor Cyan
    az containerapp ingress sticky-sessions set `
        --name $ContainerAppName `
        --resource-group $ResourceGroup `
        --affinity sticky `
        --output none

    if ($LASTEXITCODE -ne 0) {
        throw "Container App sticky-session configuration failed"
    }

    $postDeployScript = Join-Path $RepoRoot 'scripts/configure_api_postdeploy.py'
    python $postDeployScript --profile api --name $ContainerAppName `
        --resource-group $ResourceGroup
    if ($LASTEXITCODE -ne 0) {
        throw "Container App health-probe configuration failed"
    }
    
    Write-Host "[OK] Image and environment variables updated atomically" -ForegroundColor Green
    Write-Host "[OK] Deployment initiated successfully" -ForegroundColor Green
    
} catch {
    Write-Host "[ERROR] Deployment failed: $_" -ForegroundColor Red
    exit 1
}

# Wait for deployment to stabilize
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "STEP 3/3: VERIFYING DEPLOYMENT" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "[Waiting for deployment to stabilize (30 seconds)]" -ForegroundColor Yellow
Start-Sleep -Seconds 30

# Get Container App details
Write-Host ""
Write-Host "[Container App Status]" -ForegroundColor Cyan
try {
    $appDetails = az containerapp show `
        --name $ContainerAppName `
        --resource-group $ResourceGroup `
        --output json | ConvertFrom-Json
    
    $fqdn = $appDetails.properties.configuration.ingress.fqdn
    $status = $appDetails.properties.runningStatus
    $latestRevision = $appDetails.properties.latestRevisionName
    
    Write-Host "   Status: $status" -ForegroundColor $(if ($status -eq "Running") { "Green" } else { "Yellow" })
    Write-Host "   Latest Revision: $latestRevision" -ForegroundColor Gray
    Write-Host "   URL: https://$fqdn" -ForegroundColor Gray
    
    # Health check
    Write-Host ""
    Write-Host "[Performing health check]" -ForegroundColor Cyan
    try {
        $response = Invoke-WebRequest -Uri "https://$fqdn/api/health" -Method GET -UseBasicParsing -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            Write-Host "[OK] Health check PASSED - API is responding" -ForegroundColor Green
        } else {
            Write-Host "[WARN] Health check returned status: $($response.StatusCode)" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "[WARN] Health check failed - API may still be starting up" -ForegroundColor Yellow
        Write-Host "   Error: $_" -ForegroundColor Gray
    }
    
} catch {
    Write-Host "[WARN] Could not retrieve Container App details" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "BACKEND DEPLOYMENT COMPLETE!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Backend API URL: https://$fqdn" -ForegroundColor Cyan
Write-Host "View logs: az containerapp logs show --name $ContainerAppName --resource-group $ResourceGroup --follow" -ForegroundColor Gray
Write-Host ""
