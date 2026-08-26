#Requires -Modules Pester
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT

BeforeAll {
    $script:BashDeployment = Get-Content (
        Join-Path $PSScriptRoot '../../../scripts/deploy-backend.sh'
    ) -Raw
    $script:PowerShellDeployment = Get-Content (
        Join-Path $PSScriptRoot '../../container-app/deploy-backend.ps1'
    ) -Raw
    $script:FrontendDeployment = Get-Content (
        Join-Path $PSScriptRoot '../../web-ui/deploy-frontend.ps1'
    ) -Raw
    $script:MasterDeployment = Get-Content (
        Join-Path $PSScriptRoot '../../deploy-all.ps1'
    ) -Raw
}

Describe 'backend deployment origin controls' -Tag 'Unit' {
    It 'Does not default the Bash deployment to wildcard CORS' {
        $script:BashDeployment | Should -Match 'CORS_ORIGINS="\$\{CORS_ORIGINS:-\}"'
        $script:BashDeployment | Should -Match 'https://\$\{web_host\},http://localhost:5173'
    }

    It 'Replaces any wildcard CORS token in the PowerShell deployment' {
        $script:PowerShellDeployment | Should -Match '\$corsTokens -contains ''\*'''
        $script:PowerShellDeployment | Should -Match 'az webapp show'
        $script:PowerShellDeployment | Should -Not -Match 'webapp list[^\r\n]+\[0\]\.defaultHostName'
        $script:PowerShellDeployment | Should -Match 'http://localhost:5173'
    }

    It 'Preserves all existing values and secret references during image updates' {
        $script:PowerShellDeployment | Should -Match 'secretref:\$\(\$env\.secretRef\)'
        $script:PowerShellDeployment | Should -Match '\$currentEnv\.GetEnumerator\(\)'
    }

    It 'Repairs API ingress after replacing a bootstrap image' {
        $script:PowerShellDeployment | Should -Match 'containerapp ingress update'
        $script:PowerShellDeployment | Should -Match 'target-port 8080'
        $script:BashDeployment | Should -Match 'quickstart:latest" \\\s+--target-port 80'
        $script:BashDeployment | Should -Match 'Setting ingress target port to 8080 for the API image'
        $script:PowerShellDeployment | Should -Match 'configure_api_postdeploy\.py'
        $script:BashDeployment | Should -Match 'configure_api_postdeploy\.py'
    }

    It 'Builds the standalone frontend against the exact API origin' {
        $script:FrontendDeployment | Should -Match '\$env:VITE_API_BASE_URL = \$ApiBaseUrl'
        $script:FrontendDeployment | Should -Match 'properties\.configuration\.ingress\.fqdn'
        $script:MasterDeployment | Should -Match 'ContainerAppName = \$ContainerAppName'
    }
}