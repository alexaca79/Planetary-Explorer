#Requires -Modules Pester
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT

Describe 'Test-AzureOpenAIModelContract' -Tag 'Unit' {
    BeforeAll {
        . (Join-Path $PSScriptRoot '../select-region.ps1')
    }

    It 'Matches the location catalog sibling skuName field' {
        # Arrange
        $CatalogEntry = [pscustomobject]@{
            model = [pscustomobject]@{
                name = 'gpt-4o'
                version = '2024-11-20'
            }
            skuName = 'Standard'
        }
        $Contract = @{ Version = '2024-11-20'; Sku = 'Standard' }

        # Act
        $Result = Test-AzureOpenAIModelContract `
            -CatalogEntry $CatalogEntry `
            -RequiredModel 'gpt-4o' `
            -Contract $Contract

        # Assert
        $Result | Should -Be $true
    }

    It 'Rejects an entry that exposes only the account-scoped nested SKU shape' {
        # Arrange
        $CatalogEntry = [pscustomobject]@{
            model = [pscustomobject]@{
                name = 'gpt-4o'
                version = '2024-11-20'
                skus = @([pscustomobject]@{ name = 'Standard' })
            }
        }
        $Contract = @{ Version = '2024-11-20'; Sku = 'Standard' }

        # Act
        $Result = Test-AzureOpenAIModelContract `
            -CatalogEntry $CatalogEntry `
            -RequiredModel 'gpt-4o' `
            -Contract $Contract

        # Assert
        $Result | Should -Be $false
    }
}