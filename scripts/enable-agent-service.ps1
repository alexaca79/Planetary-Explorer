# enable-agent-service.ps1
# Programmatically enables Azure AI Agent Service on an existing AI Foundry (AIServices) account.
#
# What this script does:
#   1. Enables allowProjectManagement on the CogSvc account
#   2. Creates a CogSvc project sub-resource (required for Agent Service)
#   3. Creates account-level capability host (capabilityHostKind=Agents)
#   4. Creates project-level capability host
#   5. Assigns required roles to the container app managed identity
#   6. Updates the container app env var with the correct endpoint
#
# Prerequisites:
#   - Azure CLI logged in (az login)
#   - Contributor + User Access Administrator on the resource group
#
# Usage:
#   .\scripts\enable-agent-service.ps1

param(
    [string]$SubscriptionId = "",
    [string]$ResourceGroup = "rg-planetaryexplorer",
    [string]$AccountName = "",
    [string]$ProjectName = "planetary-explorer-agents",
    [string]$ContainerAppName = "",
    [string]$ApiVersion = "2025-04-01-preview"
)

$ErrorActionPreference = "Stop"

# Auto-discover values if not provided
if ([string]::IsNullOrEmpty($SubscriptionId)) {
    $SubscriptionId = az account show --query id -o tsv
    Write-Host "Using current subscription: $SubscriptionId" -ForegroundColor Cyan
}

if ([string]::IsNullOrEmpty($AccountName)) {
    $accounts = @(az cognitiveservices account list --resource-group $ResourceGroup `
        --query "[?kind=='AIServices']" -o json | ConvertFrom-Json)
    if ($accounts.Count -ne 1) {
        throw "Expected exactly one AI Foundry account, found $($accounts.Count). Pass -AccountName."
    }
    $AccountName = $accounts[0].name
    Write-Host "Discovered AI Foundry account: $AccountName" -ForegroundColor Cyan
}

$account = az cognitiveservices account show --name $AccountName `
    --resource-group $ResourceGroup -o json | ConvertFrom-Json
if (-not $account) {
    throw "AI Foundry account '$AccountName' was not found in '$ResourceGroup'."
}

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
            --output json | ConvertFrom-Json)
        $apiApps = @(
            $containerApps | Where-Object {
                $_.tags.'azd-service-name' -in @('api', 'web') -or
                $_.name -like 'ca-web-*'
            }
        )
        if ($apiApps.Count -ne 1) {
            throw "Expected exactly one API Container App tagged azd-service-name=api, found $($apiApps.Count). Pass -ContainerAppName."
        }
        $ContainerAppName = $apiApps[0].name
    }
    Write-Host "Discovered API Container App: $ContainerAppName" -ForegroundColor Cyan
}
$baseUrl = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.CognitiveServices/accounts/$AccountName"
$scope = $account.id

function Wait-ForProvisioning {
    param([string]$Url, [int]$TimeoutSeconds = 120)
    $elapsed = 0
    while ($elapsed -lt $TimeoutSeconds) {
        Start-Sleep -Seconds 10
        $elapsed += 10
        $state = az rest --method get --url "$Url`?api-version=$ApiVersion" --query "properties.provisioningState" -o tsv 2>$null
        Write-Host "  State: $state ($elapsed`s)"
        if ($state -eq "Succeeded") { return $true }
        if ($state -eq "Failed") { throw "Provisioning failed" }
    }
    throw "Provisioning timed out after $TimeoutSeconds seconds"
}

function Ensure-RoleAssignment {
    param(
        [Parameter(Mandatory=$true)]
        [string]$PrincipalId,
        [Parameter(Mandatory=$true)]
        [string]$Role,
        [Parameter(Mandatory=$true)]
        [string]$Scope
    )

    $assignmentId = az role assignment list `
        --assignee-object-id $PrincipalId `
        --role $Role `
        --scope $Scope `
        --include-inherited `
        --fill-principal-name false `
        --query '[0].id' -o tsv
    if (-not $assignmentId) {
        az role assignment create `
            --assignee-object-id $PrincipalId `
            --assignee-principal-type ServicePrincipal `
            --role $Role `
            --scope $Scope `
            -o none
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to assign required role '$Role' to '$PrincipalId'."
        }
        $assignmentId = az role assignment list `
            --assignee-object-id $PrincipalId `
            --role $Role `
            --scope $Scope `
            --include-inherited `
            --fill-principal-name false `
            --query '[0].id' -o tsv
    }
    if (-not $assignmentId) {
        throw "Required role '$Role' was not verified for '$PrincipalId'."
    }
}

# Step 1: Enable allowProjectManagement
Write-Host "`n=== Step 1: Enable allowProjectManagement ===" -ForegroundColor Cyan
az resource update `
    --ids $account.id `
    --api-version $ApiVersion `
    --set properties.allowProjectManagement=true properties.disableLocalAuth=true `
    --output none
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to enable Agent Service account management.'
}
Wait-ForProvisioning -Url $baseUrl

# Step 2: Create CogSvc project sub-resource
Write-Host "`n=== Step 2: Create CogSvc project '$ProjectName' ===" -ForegroundColor Cyan
$projectBody = @{
    location = $account.location
    identity = @{ type = "SystemAssigned" }
    properties = @{
        description = "Planetary Explorer GEOINT Agent Project"
        displayName = "Planetary Explorer Agents"
    }
} | ConvertTo-Json -Depth 3
$projectFile = [System.IO.Path]::GetTempFileName()
$projectBody | Set-Content -Path $projectFile -Encoding utf8

$projectUrl = "$baseUrl/projects/$ProjectName"
$result = az rest --method put --url "$projectUrl`?api-version=$ApiVersion" --body "@$projectFile" --query "properties.provisioningState" -o tsv 2>&1
Write-Host "  Project state: $result"
if ($result -ne "Succeeded") { Wait-ForProvisioning -Url $projectUrl }
Remove-Item $projectFile

$projectPrincipalId = az rest --method get `
    --url "$projectUrl`?api-version=$ApiVersion" `
    --query identity.principalId -o tsv
if (-not $projectPrincipalId) {
    throw "Agent Service project '$ProjectName' has no managed identity principal."
}
Ensure-RoleAssignment -PrincipalId $projectPrincipalId -Role 'Foundry User' -Scope $scope

# Step 3: Create account-level capability host
Write-Host "`n=== Step 3: Create account capability host ===" -ForegroundColor Cyan
$capHostBody = '{"properties":{"capabilityHostKind":"Agents"}}'
$capFile = [System.IO.Path]::GetTempFileName()
$capHostBody | Set-Content -Path $capFile -Encoding utf8

$acctCapUrl = "$baseUrl/capabilityHosts/default"
$result = az rest --method put --url "$acctCapUrl`?api-version=$ApiVersion" --body "@$capFile" --query "properties.provisioningState" -o tsv 2>&1
Write-Host "  Account CapHost state: $result"
if ($result -ne "Succeeded") { Wait-ForProvisioning -Url $acctCapUrl }
Remove-Item $capFile

# Step 4: Create project-level capability host
Write-Host "`n=== Step 4: Create project capability host ===" -ForegroundColor Cyan
$projCapFile = [System.IO.Path]::GetTempFileName()
$capHostBody | Set-Content -Path $projCapFile -Encoding utf8

$projCapUrl = "$projectUrl/capabilityHosts/default"
$result = az rest --method put --url "$projCapUrl`?api-version=$ApiVersion" --body "@$projCapFile" --query "properties.provisioningState" -o tsv 2>&1
Write-Host "  Project CapHost state: $result"
if ($result -ne "Succeeded") { Wait-ForProvisioning -Url $projCapUrl }
Remove-Item $projCapFile

# Step 5: Assign roles to container app managed identity
Write-Host "`n=== Step 5: Assign roles to container app MI ===" -ForegroundColor Cyan
$principalId = az containerapp show -n $ContainerAppName -g $ResourceGroup --query "identity.principalId" -o tsv 2>$null
Write-Host "  Container app MI: $principalId"

$roles = @("Foundry User", "Cognitive Services OpenAI Contributor")
foreach ($role in $roles) {
    Write-Host "  Assigning: $role"
    Ensure-RoleAssignment -PrincipalId $principalId -Role $role -Scope $scope
}

# Step 6: Update container app env var
Write-Host "`n=== Step 6: Update AZURE_AI_PROJECT_ENDPOINT ===" -ForegroundColor Cyan
$endpoint = "https://$AccountName.services.ai.azure.com/api/projects/$ProjectName"
Write-Host "  Endpoint: $endpoint"
az containerapp update -n $ContainerAppName -g $ResourceGroup --set-env-vars "AZURE_AI_PROJECT_ENDPOINT=$endpoint" -o none 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to update AZURE_AI_PROJECT_ENDPOINT.'
}
$configuredEndpoint = az containerapp show -n $ContainerAppName -g $ResourceGroup `
    --query "properties.template.containers[0].env[?name=='AZURE_AI_PROJECT_ENDPOINT'].value | [0]" `
    -o tsv
if ($configuredEndpoint -ne $endpoint) {
    throw 'AZURE_AI_PROJECT_ENDPOINT verification failed.'
}

# Step 7: Verify
Write-Host "`n=== Verification ===" -ForegroundColor Green
$token = az account get-access-token --resource "https://ai.azure.com" --query accessToken -o tsv 2>$null
try {
    $r = Invoke-RestMethod -Uri "$endpoint/agents?api-version=2025-05-15-preview" -Headers @{"Authorization"="Bearer $token"} -Method Get
    Write-Host "  Agent Service API: SUCCESS (agents: $($r.data.Count))" -ForegroundColor Green
} catch {
    Write-Host "  Agent Service API: FAILED - $($_.Exception.Message)" -ForegroundColor Red
    throw
}

Write-Host "`nDone! Agent Service is enabled." -ForegroundColor Green
