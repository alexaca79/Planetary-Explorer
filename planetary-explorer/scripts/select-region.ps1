#!/usr/bin/env pwsh
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
#Requires -Version 7.0

# Auto-select an Azure region that can host the full Planetary Explorer stack.
#
# Strategy:
#   1. Walk a curated candidate list (regions historically reliable for AOAI + Container Apps + AI Search).
#   2. For each candidate, verify that every required resource provider lists the region.
#   3. For Azure OpenAI, verify every requested model is published in the region
#      and that the subscription has any remaining capacity.
#   4. Print the first region that passes. Exit non-zero if none do.
#
# Designed for unattended use from deploy-infrastructure.ps1 — emits ONLY the chosen region
# on stdout; diagnostics go to stderr so callers can do:  $loc = pwsh ./select-region.ps1
#
# Flags mirror the master deploy script so the preflight requires exactly what will be deployed.
[CmdletBinding()]
param(
    [string[]]$Candidates = @('eastus2','swedencentral','westus3','australiaeast','uksouth','francecentral'),
    [Alias('RequiredOpenAiModel')]
    [string[]]$RequiredOpenAiModels = @(),
    [bool]$DeployGpt5 = $true,
    [bool]$DeployGpt56 = $true,
    [bool]$DeployEmbeddingModel = $true,
    [switch]$EnableFabric,
    [switch]$EnablePrivateEndpoints,
    [switch]$EnableMpcPro
)

$ErrorActionPreference = 'Stop'

$KnownModelContracts = @{
    'gpt-4o' = @{ Version = '2024-11-20'; Sku = 'Standard'; Capacity = 10 }
    'gpt-4.1-mini' = @{ Version = '2025-04-14'; Sku = 'Standard'; Capacity = 10; QuotaModel = 'gpt4.1-mini' }
    'gpt-5' = @{ Version = '2025-08-07'; Sku = 'GlobalStandard'; Capacity = 10 }
    'gpt-5.6-sol' = @{ Version = '2026-07-09'; Sku = 'GlobalStandard'; Capacity = 10 }
    'gpt-5.6-terra' = @{ Version = '2026-07-09'; Sku = 'GlobalStandard'; Capacity = 10 }
    'gpt-5.6-luna' = @{ Version = '2026-07-09'; Sku = 'GlobalStandard'; Capacity = 10 }
    'text-embedding-3-small' = @{ Version = '1'; Sku = 'Standard'; Capacity = 30 }
}

if ($PSBoundParameters.ContainsKey('RequiredOpenAiModels')) {
    $RequiredModelNames = @($RequiredOpenAiModels)
} else {
    $RequiredModelNames = @('gpt-4o', 'gpt-4.1-mini')
    if ($DeployGpt5) { $RequiredModelNames += 'gpt-5' }
    if ($DeployGpt56) {
        $RequiredModelNames += @('gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna')
    }
    if ($DeployEmbeddingModel) { $RequiredModelNames += 'text-embedding-3-small' }
}

function Write-Info($msg) { Write-Host $msg -ForegroundColor Gray -ErrorAction SilentlyContinue }

# Required providers/resource types for the base stack.
$required = @(
    @{ ns = 'Microsoft.App';               type = 'managedEnvironments' },
    @{ ns = 'Microsoft.Web';               type = 'sites' },
    @{ ns = 'Microsoft.ContainerRegistry'; type = 'registries' },
    @{ ns = 'Microsoft.CognitiveServices'; type = 'accounts' },
    @{ ns = 'Microsoft.KeyVault';          type = 'vaults' },
    @{ ns = 'Microsoft.Storage';           type = 'storageAccounts' },
    @{ ns = 'Microsoft.OperationalInsights'; type = 'workspaces' }
)
if ($EnableFabric)           { $required += @{ ns = 'Microsoft.Fabric';  type = 'capacities' } }
if ($EnablePrivateEndpoints) { $required += @{ ns = 'Microsoft.Network'; type = 'privateEndpoints' } }

# Pre-fetch each provider's location list once (cache outside the candidate loop).
$providerLocs = @{}
foreach ($svc in $required) {
    $key = "$($svc.ns)/$($svc.type)"
    if (-not $providerLocs.ContainsKey($key)) {
        $locs = az provider show --namespace $svc.ns `
            --query "resourceTypes[?resourceType=='$($svc.type)'].locations[]" -o tsv 2>$null
        if (-not $locs) { $locs = @() }
        # Normalize "East US 2" -> "eastus2"
        $providerLocs[$key] = @($locs | ForEach-Object { ($_ -replace '\s','').ToLower() })
    }
}

function Test-Region {
    param([string]$Region)

    $norm = ($Region -replace '\s','').ToLower()

    foreach ($svc in $required) {
        $key = "$($svc.ns)/$($svc.type)"
        if ($providerLocs[$key].Count -eq 0) {
            Write-Info "  [skip-check] $key returned no location list (provider may not be registered)"
            continue
        }
        if ($providerLocs[$key] -notcontains $norm) {
            Write-Info "  [fail] $key not available in $Region"
            return $false
        }
    }

    # AOAI model availability + capacity check.
    try {
        $models = az cognitiveservices model list --location $Region -o json 2>$null | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or -not $models) {
            Write-Info "  [fail] could not list AOAI models in $Region"
            return $false
        }
        $usage = az cognitiveservices usage list --location $Region -o json 2>$null | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or -not $usage) {
            Write-Info "  [fail] could not list AOAI quota in $Region"
            return $false
        }
        foreach ($RequiredModel in $RequiredModelNames) {
            $Contract = $KnownModelContracts[$RequiredModel]
            if (-not $Contract) {
                Write-Info "  [fail] no deployment contract is defined for '$RequiredModel'"
                return $false
            }
            $Hit = @($models | Where-Object {
                $_.model.name -eq $RequiredModel -and
                $_.model.version -eq $Contract.Version -and
                @($_.model.skus | ForEach-Object { $_.name }) -contains $Contract.Sku
            })
            if ($Hit.Count -eq 0) {
                Write-Info "  [fail] AOAI model '$RequiredModel' version '$($Contract.Version)' with SKU '$($Contract.Sku)' is unavailable in $Region"
                return $false
            }
            $QuotaModel = if ($Contract.QuotaModel) { $Contract.QuotaModel } else { $RequiredModel }
            $QuotaName = "OpenAI.$($Contract.Sku).$QuotaModel"
            $Quota = @($usage | Where-Object { $_.name.value -eq $QuotaName } | Select-Object -First 1)
            if ($Quota.Count -eq 0) {
                Write-Info "  [fail] quota '$QuotaName' is unavailable in $Region"
                return $false
            }
            $AvailableCapacity = [double]$Quota[0].limit - [double]$Quota[0].currentValue
            if ($AvailableCapacity -lt [double]$Contract.Capacity) {
                Write-Info "  [fail] quota '$QuotaName' has $AvailableCapacity remaining; $($Contract.Capacity) is required"
                return $false
            }
        }
    } catch {
        Write-Info "  [fail] AOAI model or quota check threw in $Region`: $($_.Exception.Message)"
        return $false
    }

    return $true
}

Write-Info "Selecting region from: $($Candidates -join ', ')"

foreach ($r in $Candidates) {
    Write-Info "Checking $r ..."
    if (Test-Region -Region $r) {
        Write-Info "[OK] selected $r"
        # ONLY emit the region on stdout — callers capture this.
        Write-Output $r
        exit 0
    }
}

Write-Error "No candidate region satisfies the required services. Tried: $($Candidates -join ', ')"
exit 1
