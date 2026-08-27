#Requires -Modules Pester
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT

BeforeAll {
    $script:DeploymentScript = Get-Content (
        Join-Path $PSScriptRoot '../../../deploy-infrastructure.ps1'
    ) -Raw
    $script:Workflow = Get-Content (
        Join-Path $PSScriptRoot '../../../.github/workflows/deploy.yml'
    ) -Raw
}

Describe 'deploy-infrastructure release gates' -Tag 'Unit' {
    It 'Runs the complete preflight for pinned regions' {
        $script:DeploymentScript | Should -Match '\$pinnedParams\.Candidates = @\(\$Location\)'
        $script:DeploymentScript | Should -Not -Match 'if \(\$deployGeoFmResolved\) \{\s*Write-Host "Validating GeoFM'
    }

    It 'Builds and publishes both GeoFM service images' {
        $script:DeploymentScript | Should -Match 'deployGeoFmServices=\$\(\$deployGeoFmResolved'
        $script:DeploymentScript | Should -Match 'planetary-explorer-geofm-mcp:'
        $script:DeploymentScript | Should -Match 'planetary-explorer-geofm-worker:'
        $script:DeploymentScript | Should -Match 'Dockerfile\.worker'
    }

    It 'Rejects bootstrap-image success without runtime verification' {
        $script:DeploymentScript | Should -Match 'properties\.healthState'
        $script:DeploymentScript | Should -Match 'localhost:8080/ready'
        $script:DeploymentScript | Should -Match 'workerMinReplicas -ne "0"'
    }

    It 'Requires a distinct GeoFM owner-signing key' {
        $script:DeploymentScript | Should -Match 'GeoFmOwnerSigningKey\.Length -lt 32'
        $script:DeploymentScript | Should -Match 'geoFmOwnerSigningKey=\$GeoFmOwnerSigningKey'
        $script:DeploymentScript | Should -Match 'GeoFmMcpApiKey, \$GeoFmOwnerSigningKey'
    }

    It 'Deploys a poison-message path for exhausted worker failures' {
        $geoFmBicep = Get-Content (
            Join-Path $PSScriptRoot '../../infra/app/geofm.bicep'
        ) -Raw
        $geoFmBicep | Should -Match 'geofm-poison'
        $geoFmBicep | Should -Match 'GEOFM_POISON_QUEUE_NAME'
        ([regex]::Matches($geoFmBicep, 'StorageQueueDataReader')).Count | Should -Be 2
        $geoFmBicep | Should -Match 'controlQueueReaderRole'
        $geoFmBicep | Should -Not -Match "path: '/ready'"
        $script:DeploymentScript | Should -Match '--profile geofm'
    }

    It 'Grants only the control identity artifact-link delegation' {
        $geoFmBicep = Get-Content (
            Join-Path $PSScriptRoot '../../infra/app/geofm.bicep'
        ) -Raw
        $geoFmBicep | Should -Match 'StorageBlobDelegator'
        $geoFmBicep | Should -Match 'db58b8e5-c6ad-4a2a-8342-4190687cbf4a'
    }

    It 'Never falls back to a non-API Container App' {
        $deployAll = Get-Content (
            Join-Path $PSScriptRoot '../../deploy-all.ps1'
        ) -Raw
        $deployAll | Should -Not -Match '\$ContainerAppName = \$appList\[0\]'
        $deployAll | Should -Match '\$apiApps\.Count -eq 1'
        $deployAll | Should -Match 'requires an exact API Container App target'
        $agentService = Get-Content (
            Join-Path $PSScriptRoot '../../../scripts/enable-agent-service.ps1'
        ) -Raw
        $agentService | Should -Not -Match 'containerapp list[^\r\n]+\[0\]\.name'
        $agentService | Should -Match "azd-service-name' -in @\('api', 'web'\)"
    }

    It 'Uses the same canonical API name in Bicep and deployment discovery' {
        $mainBicep = Get-Content (
            Join-Path $PSScriptRoot '../../infra/main.bicep'
        ) -Raw
        $apiBicep = Get-Content (
            Join-Path $PSScriptRoot '../../infra/app/web.bicep'
        ) -Raw
        $mainBicep | Should -Match 'param apiContainerAppName string'
        $mainBicep | Should -Match 'name: resolvedApiContainerAppName'
        $apiBicep | Should -Match "azd-service-name': 'api'"
        $script:DeploymentScript | Should -Match 'AZURE_CONTAINER_APP_NAME\.value'
        $script:DeploymentScript | Should -Not -Match 'containerapp list[^\r\n]+contains\(name'
        $script:DeploymentScript | Should -Match 'resolve_deployment_targets\.py'
    }

    It 'Does not reconcile a legacy Container Apps environment for adopted services' {
        $mainBicep = Get-Content (
            Join-Path $PSScriptRoot '../../infra/main.bicep'
        ) -Raw
        $mainBicep | Should -Match 'var resolvedContainerAppsEnvironmentName = empty\(existingContainerAppsEnvironmentName\)'
        $mainBicep | Should -Match 'var shouldDeployAppsEnvironment = empty\(existingContainerAppsEnvironmentName\) && \(shouldDeployApiContainer \|\| deployGeoFm \|\| deployMcpServer \|\| deployMpcMcp \|\| shouldDeployWebSearchMcp \|\| deployWeatherStub\)'
        $mainBicep | Should -Match "module appsEnv './shared/apps-env\.bicep' = if \(shouldDeployAppsEnvironment\)"
        $mainBicep | Should -Match 'appsEnv\.\?outputs\.\?name \?\? resolvedContainerAppsEnvironmentName'
    }

    It 'Uses either an explicit HTTPS frontend origin or the provisioned Web App origin' {
        $mainBicep = Get-Content (
            Join-Path $PSScriptRoot '../../infra/main.bicep'
        ) -Raw
        $frontendBicep = Get-Content (
            Join-Path $PSScriptRoot '../../infra/app/frontend.bicep'
        ) -Raw
        $script:DeploymentScript | Should -Match 'FrontendUrl must be an absolute HTTPS origin'
        $mainBicep | Should -Match 'resolvedFrontendUrl = empty\(frontendUrl\)'
        $frontendBicep | Should -Match "azd-service-name': 'web'"
        $mainBicep | Should -Match 'output AZURE_WEB_APP_NAME'
    }

    It 'Provisions azd service targets before packaging and repairs the API port after deploy' {
        $parameters = Get-Content (
            Join-Path $PSScriptRoot '../../infra/main.parameters.json'
        ) -Raw
        $rootManifest = Get-Content (
            Join-Path $PSScriptRoot '../../../azure.yaml'
        ) -Raw
        $nestedManifest = Get-Content (
            Join-Path $PSScriptRoot '../../azure.yaml'
        ) -Raw
        $postDeploy = Get-Content (
            Join-Path $PSScriptRoot '../../../scripts/configure_api_postdeploy.py'
        ) -Raw
        $parameters | Should -Match 'SERVICE_API_IMAGE_NAME=mcr\.microsoft\.com/k8se/quickstart:latest'
        foreach ($manifest in @($rootManifest, $nestedManifest)) {
            $manifest | Should -Match 'azd: provision'
            $manifest | Should -Match 'azd: package api'
            $manifest | Should -Match 'resourceName: \$\{AZURE_CONTAINER_APP_NAME\}'
            $manifest | Should -Match 'configure_api_postdeploy\.py'
        }
        $postDeploy | Should -Match '"targetPort"\] = API_PORT'
        $postDeploy | Should -Match '"stickySessions"\] = \{"affinity": "sticky"\}'
        $postDeploy | Should -Match '"Liveness"'
        $postDeploy | Should -Match '"Readiness"'
    }

    It 'Provisions the bootstrap API and deploys the optional Web Search image' {
        $script:DeploymentScript | Should -Match 'DeployWebSearchMcp'
        $script:DeploymentScript | Should -Match 'deployWebSearchMcp=\$\(\$deployWebSearchResolved'
        $script:DeploymentScript | Should -Match 'planetary-explorer-web-search-mcp:'
        $script:Workflow | Should -Match '--parameters deployApiContainer=true'
        $script:Workflow | Should -Match '--parameters containerImage="mcr\.microsoft\.com/k8se/quickstart:latest"'
        $script:Workflow | Should -Match 'existingContainerAppsEnvironmentName'
        $script:Workflow | Should -Match 'deploy-web-search:'
        $script:Workflow | Should -Match "azd-service-name.*web-search-mcp"
        $script:Workflow | Should -Match 'planetary-explorer-web-search-mcp:\$TAG'
        $script:Workflow | Should -Match '--profile web-search'
        $script:Workflow | Should -Match 'PUBLIC_DEMO_MODE:.*github\.event\.inputs\.disable_auth'
        $script:Workflow | Should -Match 'containerapp registry set'
        $script:Workflow | Should -Match '--agent-pool.*\$AGENT_POOL'
        $script:Workflow | Should -Match 'TEMP_BUILD_ACR'
        $script:Workflow | Should -Match 'az acr import'
        $script:Workflow | Should -Match 'WEB_SEARCH_MCP_URL=\$WEB_SEARCH_URL'
        $script:DeploymentScript | Should -Match 'existingContainerAppsEnvironmentName=\$existingContainerAppsEnvironmentName'
        $script:DeploymentScript | Should -Match 'temporaryBuildRegistry'
        $script:DeploymentScript | Should -Match 'acr import'
    }

    It 'Does not interpolate free-form dispatch inputs into shell source' {
        $freeFormInputs = @(
            'web_app_name',
            'mpc_pro_stac_url',
            'fabric_capacity_resource_id',
            'weather_stub_image_name',
            'aurora_endpoint_url',
            'earth2_fcn_endpoint_url',
            'mai_weather_endpoint_url'
        ) -join '|'
        $shellInterpolation = '\$\{\{\s*github\.event\.inputs\.(' + $freeFormInputs + ')'
        $workflowBody = ($script:Workflow -split 'jobs:', 2)[1]
        $workflowBody | Should -Not -Match $shellInterpolation
    }

    It 'Deploys backend changes made through root runtime scripts' {
        $script:Workflow | Should -Match 'scripts/\(deploy-backend\\\.sh\|configure_api_postdeploy\\\.py\|enable-agent-service\\\.ps1\)'
        $script:Workflow | Should -Match 'BACKEND_CHANGED=true'
    }

    It 'Fails closed by default and disables Foundry local authentication' {
        $apiBicep = Get-Content (
            Join-Path $PSScriptRoot '../../infra/app/web.bicep'
        ) -Raw
        $foundryBicep = Get-Content (
            Join-Path $PSScriptRoot '../../infra/shared/ai-foundry.bicep'
        ) -Raw
        $apiBicep | Should -Match 'publicDemoMode && !enableAuthentication'
        $foundryBicep | Should -Match 'disableLocalAuth: true'
        $foundryBicep | Should -Match '53ca6127-db72-4b80-b1b0-d745d6d5456d'
        $foundryBicep | Should -Match 'agentProject\.\?identity\.\?principalId'
    }

    It 'Uses one configurable Agent Service project name' {
        $mainBicep = Get-Content (
            Join-Path $PSScriptRoot '../../infra/main.bicep'
        ) -Raw
        $mainBicep | Should -Match "param agentProjectName string = 'planetary-explorer-agents'"
        $script:Workflow | Should -Match "AGENT_PROJECT_NAME:.*planetary-explorer-agents"
        $script:Workflow | Should -Match 'PROJECT_NAME="\$AGENT_PROJECT_NAME"'
        $script:Workflow | Should -Match 'ensure_role_assignment "\$PROJECT_PRINCIPAL_ID" "Foundry User"'
    }

    It 'Adopts existing azd targets before provisioning' {
        $rootManifest = Get-Content (
            Join-Path $PSScriptRoot '../../../azure.yaml'
        ) -Raw
        $nestedManifest = Get-Content (
            Join-Path $PSScriptRoot '../../azure.yaml'
        ) -Raw
        foreach ($manifest in @($rootManifest, $nestedManifest)) {
            $manifest | Should -Match 'preprovision:'
            $manifest | Should -Match 'resolve_azd_deployment_targets\.py'
            $manifest | Should -Not -Match 'run:\s+\S+\.py\s+--'
            $manifest | Should -Not -Match 'kind:\s+python'
            $manifest | Should -Match 'shell:\s+pwsh'
            $manifest | Should -Match 'shell:\s+sh'
        }
    }

    It 'Treats Agent Service RBAC and verification as mandatory' {
        $agentService = Get-Content (
            Join-Path $PSScriptRoot '../../../scripts/enable-agent-service.ps1'
        ) -Raw
        $script:Workflow | Should -Match 'ensure_role_assignment'
        $script:Workflow | Should -Match 'Required role.*was not assigned'
        $script:Workflow | Should -Not -Match 'Foundry User role already assigned'
        $agentService | Should -Match 'Ensure-RoleAssignment'
        $agentService | Should -Match 'properties\.allowProjectManagement=true properties\.disableLocalAuth=true'
        $agentService | Should -Match 'location = \$account\.location'
        $agentService | Should -Match "Role 'Foundry User'"
        $agentService | Should -Not -Match 'location = "eastus2"'
        $agentService | Should -Not -Match 'publicNetworkAccess = "Enabled"'
    }

    It 'Uses the shared resolver in every workflow deployment job' {
        ([regex]::Matches($script:Workflow, 'resolve_deployment_targets\.py')).Count | Should -BeGreaterOrEqual 4
        $script:Workflow | Should -Match 'web_app_name: \$\{\{ steps\.discover\.outputs\.web_app_name \}\}'
        $script:Workflow | Should -Match 'needs\.deploy-frontend\.outputs\.web_app_name \|\| needs\.deploy-backend\.outputs\.web_app_name'
    }

    It 'Preserves network and authentication posture on push' {
        $script:Workflow | Should -Match 'Push deployment will preserve and verify the existing authentication mode'
        $script:Workflow | Should -Match 'Preserve Existing Authentication Mode'
        $script:Workflow | Should -Match 'PRIVATE_ACR_COUNT'
        $script:Workflow | Should -Match 'private_endpoints_enabled'
        $script:Workflow | Should -Not -Match 'Ensure public network access'
        $script:Workflow | Should -Not -Match 'Purge Soft-Deleted Resources'
    }

    It 'Serializes all branches targeting the same resource group' {
        $script:Workflow | Should -Match "group: deploy-\$\{\{ vars\.RESOURCE_GROUP \|\| 'rg-planetaryexplorer' \}\}"
        $script:Workflow | Should -Not -Match 'group: deploy-\$\{\{ github\.ref \}\}'
    }

    It 'Publishes both GeoFM services in enabled automated release paths' {
        $rootManifest = Get-Content (
            Join-Path $PSScriptRoot '../../../azure.yaml'
        ) -Raw
        $optionalDeploy = Get-Content (
            Join-Path $PSScriptRoot '../../../scripts/deploy_optional_azd_services.py'
        ) -Raw
        $rootManifest | Should -Match 'deploy_optional_azd_services\.py'
        $optionalDeploy | Should -Match '"deploy", "geofm"'
        $optionalDeploy | Should -Match '"deploy", "geofm-worker"'
        $script:Workflow | Should -Match 'Deploy GeoFM Control Plane and Worker'
        $script:Workflow | Should -Match 'vars\.GEOFM_RESOURCE_GROUP'
        $script:Workflow | Should -Match 'planetary-explorer-geofm-worker:'
        $script:Workflow | Should -Match '--profile geofm'
        $script:Workflow | Should -Match 'Secure ACR has no active agent pool'
        $script:Workflow | Should -Match 'BUILD_ACR_ID=\$\(az acr show'
        $script:Workflow | Should -Match 'az acr import'
        $script:Workflow | Should -Match '--registry "\$BUILD_ACR_ID"'
    }

    It 'Requires and applies an explicit auth mode for fresh azd deployments' {
        $resolver = Get-Content (
            Join-Path $PSScriptRoot '../../../scripts/resolve_deployment_targets.py'
        ) -Raw
        $rootManifest = Get-Content (
            Join-Path $PSScriptRoot '../../../azure.yaml'
        ) -Raw
        $resolver | Should -Match 'Fresh deployments must set exactly one'
        $rootManifest | Should -Match 'configure_auth_postdeploy\.py'
        $script:DeploymentScript | Should -Match 'Fresh deployments require exactly one'
    }
}