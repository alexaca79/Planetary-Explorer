metadata name = 'Chat History Data Access'
metadata description = 'Grants the API managed identity access to chat history and artifact data.'

@description('Name of the Cosmos DB account containing chat history.')
param cosmosAccountName string

@description('Name of the Cosmos DB for NoSQL database.')
param cosmosDatabaseName string

@description('Name of the Cosmos DB chat history container.')
param cosmosContainerName string

@description('Name of the storage account containing chat artifacts.')
param storageAccountName string

@description('Name of the private Blob container containing chat artifacts.')
param blobContainerName string

@description('Object ID of the API Container App managed identity.')
param principalId string

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = {
  name: cosmosAccountName
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' existing = {
  parent: storageAccount
  name: 'default'
}

resource artifactContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' existing = {
  parent: blobService
  name: blobContainerName
}

var cosmosDataContributorRole = '00000000-0000-0000-0000-000000000002'
var storageBlobDataContributorRole = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource cosmosDataAccess 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = if (!empty(principalId)) {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, principalId, cosmosDataContributorRole, cosmosContainerName)
  properties: {
    principalId: principalId
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/${cosmosDataContributorRole}'
    scope: '${cosmosAccount.id}/dbs/${cosmosDatabaseName}/colls/${cosmosContainerName}'
  }
}

resource blobDataAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(artifactContainer.id, principalId, storageBlobDataContributorRole)
  scope: artifactContainer
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      storageBlobDataContributorRole
    )
  }
}