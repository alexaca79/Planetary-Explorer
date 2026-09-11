targetScope = 'resourceGroup'
metadata name = 'Existing Environment History Upgrade'
metadata description = 'Adds private history access without replacing the public API, storage, Cosmos account, or existing network.'

@description('Existing Cosmos DB account name in this resource group.')
param cosmosAccountName string
@description('Existing storage account name in this resource group.')
param storageAccountName string
@description('Existing registry name in this resource group.')
param registryName string
@description('Existing network and Container Apps resource group.')
param networkResourceGroupName string
@description('Existing VNet name.')
param vnetName string
@description('Existing private endpoint subnet name.')
param privateEndpointSubnetName string
@description('Existing Container Apps environment name.')
param containerAppsEnvironmentName string
@description('Location of the existing VNet and environment.')
param networkLocation string
@description('New dedicated memory Search service name.')
param searchServiceName string
@description('Location of the new Search service.')
param searchLocation string
@description('New history Container App name.')
param historyAppName string
@description('New history managed identity name.')
param historyIdentityName string
@description('Immutable tested backend image reference.')
param image string
@description('Tenant ID for validated user authentication.')
param tenantId string
@description('Application token audience for user authentication.')
param clientId string
@description('Existing frontend App Service requiring optional history sign-in.')
param frontendWebAppName string
@description('Cosmos DB database name.')
param databaseName string = 'planetary-explorer'
@description('Cosmos DB chat container name.')
param containerName string = 'chat-history'
@description('Artifact Blob container name.')
param artifactContainerName string = 'chat-artifacts'
@description('Dedicated memory Search index name.')
param memoryIndexName string = 'chat-memory-v1'
@description('Tags for new resources.')
param tags object = { workload: 'planetary-explorer-chat-memory' }

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = { name: cosmosAccountName }
resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' existing = { name: storageAccountName }
resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' existing = { parent: storage, name: 'default' }
resource artifacts 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' existing = {
  parent: blobs
  name: artifactContainerName
}
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = { name: registryName }
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: historyIdentityName
  location: networkLocation
  tags: tags
}
var acrPullRole = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
resource registryAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, acrPullRole)
  scope: registry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRole)
  }
}
module dataAccess './shared/chat-history-access.bicep' = {
  name: 'history-private-data-access'
  params: {
    cosmosAccountName: cosmos.name
    cosmosDatabaseName: databaseName
    cosmosContainerName: containerName
    storageAccountName: storage.name
    blobContainerName: artifacts.name
    principalId: identity.properties.principalId
  }
}
module search './shared/chat-memory-search.bicep' = {
  name: 'history-private-search'
  params: { name: searchServiceName, location: searchLocation, tags: tags, enablePrivateEndpoints: true }
}
module searchAccess './shared/chat-memory-access.bicep' = {
  name: 'history-private-search-access'
  params: { searchServiceName: search.outputs.name, principalId: identity.properties.principalId }
}
module networking './shared/chat-history-private-network.bicep' = {
  name: 'history-private-network'
  scope: resourceGroup(networkResourceGroupName)
  params: {
    location: networkLocation
    vnetName: vnetName
    subnetName: privateEndpointSubnetName
    cosmosAccountId: cosmos.id
    storageAccountId: storage.id
    searchServiceId: search.outputs.id
    suffix: uniqueString(resourceGroup().id, historyAppName)
    tags: tags
  }
}
module host './app/chat-history.bicep' = {
  name: 'history-private-host'
  scope: resourceGroup(networkResourceGroupName)
  params: {
    name: historyAppName
    location: networkLocation
    environmentName: containerAppsEnvironmentName
    identityId: identity.id
    identityClientId: identity.properties.clientId
    registryServer: registry.properties.loginServer
    image: image
    tenantId: tenantId
    clientId: clientId
    cosmosEndpoint: cosmos.properties.documentEndpoint
    cosmosDatabase: databaseName
    cosmosContainer: containerName
    blobEndpoint: storage.properties.primaryEndpoints.blob
    blobContainer: artifacts.name
    searchEndpoint: search.outputs.endpoint
    memoryIndexName: memoryIndexName
    tags: tags
  }
  dependsOn: [registryAccess, dataAccess, searchAccess, networking]
}

module signIn './app/history-signin.bicep' = {
  name: 'history-optional-signin'
  params: { webAppName: frontendWebAppName, tenantId: tenantId, clientId: clientId }
}

@description('History origin for the API proxy.')
output AZURE_CHAT_HISTORY_REMOTE_URL string = host.outputs.url
@description('Dedicated Search endpoint.')
output AZURE_CHAT_MEMORY_SEARCH_ENDPOINT string = search.outputs.endpoint
@description('Dedicated Search index.')
output AZURE_CHAT_MEMORY_SEARCH_INDEX string = memoryIndexName
@description('History identity principal ID.')
output HISTORY_PRINCIPAL_ID string = identity.properties.principalId
