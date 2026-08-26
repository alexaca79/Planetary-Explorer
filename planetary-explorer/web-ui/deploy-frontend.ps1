# Planetary Explorer Frontend Deployment Script
# Deploys the React web UI to Azure App Service
# Auto-discovers resources from Azure subscription

param(
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroup = "",
    
    [Parameter(Mandatory=$false)]
    [string]$AppServiceName = "",

    [Parameter(Mandatory=$false)]
    [string]$ContainerAppName = "",

    [Parameter(Mandatory=$false)]
    [string]$ApiBaseUrl = "",
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipBuild = $false,
    
    [Parameter(Mandatory=$false)]
    [switch]$ShowDetails = $false
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "PLANETARY EXPLORER FRONTEND DEPLOYMENT" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Get script directory (web-ui folder)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "[Working Directory: $ScriptDir]" -ForegroundColor Yellow
Write-Host ""

# Check if we're in the right directory
if (-not (Test-Path "$ScriptDir\package.json")) {
    Write-Host "[ERROR] package.json not found. Are you in the web-ui directory?" -ForegroundColor Red
    exit 1
}

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

# Find App Service if not provided
if ([string]::IsNullOrEmpty($AppServiceName)) {
    Write-Host "   Looking for App Service in $ResourceGroup..." -ForegroundColor Gray
    
    $appServices = @(az webapp list --resource-group $ResourceGroup `
        --output json 2>$null | ConvertFrom-Json)
    $frontendApps = @(
        $appServices | Where-Object {
            $_.tags.'azd-service-name' -eq 'web'
        }
    )
    if ($frontendApps.Count -eq 1) {
        $AppServiceName = $frontendApps[0].name
        Write-Host "[OK] Found App Service: $AppServiceName" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] Expected exactly one App Service tagged azd-service-name=web, found $($frontendApps.Count)." -ForegroundColor Red
        Write-Host "   Please specify -AppServiceName explicitly." -ForegroundColor Yellow
        exit 1
    }
} else {
    Write-Host "[OK] Using provided App Service: $AppServiceName" -ForegroundColor Green
}

# Verify App Service exists and get details
Write-Host ""
Write-Host "[Verifying Azure App Service]" -ForegroundColor Cyan
try {
    $appService = az webapp show --name $AppServiceName --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
    Write-Host "[OK] App Service found: $($appService.defaultHostName)" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] App Service '$AppServiceName' not found in resource group '$ResourceGroup'" -ForegroundColor Red
    Write-Host "   Please verify the resource exists or update the parameters." -ForegroundColor Yellow
    exit 1
}

if ([string]::IsNullOrEmpty($ApiBaseUrl)) {
    if ([string]::IsNullOrEmpty($ContainerAppName)) {
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
            $apiApps = @(
                $containerApps | Where-Object {
                    $_.tags.'azd-service-name' -in @('api', 'web') -or
                    $_.name -like 'ca-web-*'
                }
            )
            if ($apiApps.Count -eq 1) {
                $ContainerAppName = $apiApps[0].name
            }
        }
    }
    if (-not $ContainerAppName) {
        Write-Host "[ERROR] Could not resolve the exact API Container App for the frontend build." -ForegroundColor Red
        Write-Host "   Pass -ContainerAppName or -ApiBaseUrl explicitly." -ForegroundColor Yellow
        exit 1
    }
    $apiHost = az containerapp show --name $ContainerAppName `
        --resource-group $ResourceGroup `
        --query properties.configuration.ingress.fqdn -o tsv 2>$null
    if (-not $apiHost) {
        Write-Host "[ERROR] API Container App '$ContainerAppName' has no ingress FQDN." -ForegroundColor Red
        exit 1
    }
    $ApiBaseUrl = "https://$($apiHost.Trim())"
}

$parsedApiBaseUrl = $null
if (
    -not [Uri]::TryCreate($ApiBaseUrl, [UriKind]::Absolute, [ref]$parsedApiBaseUrl) -or
    $parsedApiBaseUrl.Scheme -ne 'https' -or
    $parsedApiBaseUrl.PathAndQuery -ne '/'
) {
    Write-Host "[ERROR] ApiBaseUrl must be an absolute HTTPS origin." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Frontend API origin: $ApiBaseUrl" -ForegroundColor Green

if (-not $SkipBuild) {
    # Install dependencies
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "STEP 1/4: Installing Dependencies" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Push-Location $ScriptDir
    try {
        npm install
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed"
        }
        Write-Host "[OK] Dependencies installed" -ForegroundColor Green
    } catch {
        Write-Host "[ERROR] Failed to install dependencies: $_" -ForegroundColor Red
        Pop-Location
        exit 1
    }

    # Build the application
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "STEP 2/4: Building Production Bundle" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "This may take 2-3 minutes..." -ForegroundColor Yellow
    Write-Host ""
    try {
        $previousApiBaseUrl = $env:VITE_API_BASE_URL
        $env:VITE_API_BASE_URL = $ApiBaseUrl
        npm run build
        if ($LASTEXITCODE -ne 0) {
            throw "npm run build failed"
        }
        Write-Host ""
        Write-Host "[OK] Build completed successfully" -ForegroundColor Green
    } catch {
        Write-Host "[ERROR] Build failed: $_" -ForegroundColor Red
        Pop-Location
        exit 1
    } finally {
        $env:VITE_API_BASE_URL = $previousApiBaseUrl
    }
    Pop-Location

    # Verify dist folder exists
    if (-not (Test-Path "$ScriptDir\dist")) {
        Write-Host "[ERROR] dist folder not found after build" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host ""
    Write-Host "[SKIP] Skipping build (using existing dist folder)" -ForegroundColor Yellow
}

# Create deployment package
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "STEP 3/4: Creating Deployment Package" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
$zipPath = "$ScriptDir\deploy.zip"
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

try {
    # Build zip with POSIX forward-slash separators so Linux App Service
    # rsync can extract the entries (PowerShell 5.1 Compress-Archive writes
    # backslashes which break OneDeploy with HTTP 400).
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::Open($zipPath, 'Create')
    try {
        $distRoot = (Resolve-Path "$ScriptDir\dist").Path
        Get-ChildItem -Path $distRoot -Recurse -File | ForEach-Object {
            $relative = $_.FullName.Substring($distRoot.Length + 1).Replace('\','/')
            [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zip, $_.FullName, $relative, [System.IO.Compression.CompressionLevel]::Optimal)
        }
    } finally { $zip.Dispose() }
    $zipSize = (Get-Item $zipPath).Length / 1MB
    Write-Host "[OK] Deployment package created: $([math]::Round($zipSize, 2)) MB" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Failed to create deployment package: $_" -ForegroundColor Red
    exit 1
}

# Deploy to Azure
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "STEP 4/4: Deploying to Azure App Service" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   Resource Group: $ResourceGroup" -ForegroundColor Gray
Write-Host "   App Service: $AppServiceName" -ForegroundColor Gray
Write-Host "   This may take 1-2 minutes..." -ForegroundColor Yellow
Write-Host ""

try {
    az webapp deploy `
        --resource-group $ResourceGroup `
        --name $AppServiceName `
        --src-path $zipPath `
        --type zip `
        --output none
    
    if ($LASTEXITCODE -ne 0) {
        throw "Deployment failed"
    }
    
    Write-Host ""
    Write-Host "[OK] Deployment completed successfully!" -ForegroundColor Green
    
    # Clean up deployment package
    Remove-Item $zipPath -Force
    Write-Host "[CLEAN] Cleaned up deployment package" -ForegroundColor Gray
    
} catch {
    Write-Host "[ERROR] Deployment failed: $_" -ForegroundColor Red
    exit 1
}

# Wait for deployment to stabilize
Write-Host ""
Write-Host "[Waiting for deployment to stabilize (15 seconds)]" -ForegroundColor Yellow
Start-Sleep -Seconds 15

# Health check
Write-Host ""
Write-Host "[Performing health check]" -ForegroundColor Cyan
try {
    $response = Invoke-WebRequest -Uri "https://$($appService.defaultHostName)" -Method GET -UseBasicParsing -ErrorAction Stop
    if ($response.StatusCode -eq 200) {
        Write-Host "[OK] Health check PASSED - Frontend is responding" -ForegroundColor Green
    } else {
        Write-Host "[WARN] Health check returned status: $($response.StatusCode)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "[WARN] Health check failed - Frontend may still be starting up" -ForegroundColor Yellow
    Write-Host "   Error: $_" -ForegroundColor Gray
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "FRONTEND DEPLOYMENT COMPLETE!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Frontend URL: https://$($appService.defaultHostName)" -ForegroundColor Cyan
Write-Host "View logs: az webapp log tail --name $AppServiceName --resource-group $ResourceGroup" -ForegroundColor Gray
Write-Host ""
