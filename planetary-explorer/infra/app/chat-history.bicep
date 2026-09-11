metadata name = 'Authenticated History Worker'
metadata description = 'CPU-only chat history service on an existing VNet-enabled Container Apps environment.'

@description('History Container App name.')
param name string
@description('Location of the existing Container Apps environment.')
param location string
@description('Existing Container Apps environment name.')
param environmentName string
@description('Managed identity resource ID.')
param identityId string
@description('Managed identity client ID.')
param identityClientId string
@description('Registry login server.')
param registryServer string
@description('Immutable tested backend image reference.')
param image string
@description('Microsoft Entra tenant ID.')
param tenantId string
@description('Application-specific accepted token audience.')
param clientId string
@description('Cosmos DB endpoint.')
param cosmosEndpoint string
@description('Cosmos DB database name.')
param cosmosDatabase string
@description('Cosmos DB container name.')
param cosmosContainer string
@description('Blob service endpoint.')
param blobEndpoint string
@description('Private artifact container name.')
param blobContainer string
@description('Dedicated Search endpoint.')
param searchEndpoint string
@description('Dedicated memory index name.')
param memoryIndexName string
@description('Tags for the service.')
param tags object

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: environmentName
}
var settings = {
  AZURE_CLIENT_ID: identityClientId
  AZURE_AD_TENANT_ID: tenantId
  AZURE_AD_CLIENT_ID: clientId
  DISABLE_AUTH: 'false'
  TRUST_EASYAUTH_HEADER: 'false'
  CHAT_HISTORY_ALLOW_ANONYMOUS: 'false'
  CHAT_HISTORY_STORE: 'cosmos'
  COSMOS_CHAT_ENDPOINT: cosmosEndpoint
  COSMOS_CHAT_DATABASE: cosmosDatabase
  COSMOS_CHAT_CONTAINER: cosmosContainer
  CHAT_ARTIFACT_STORE: 'blob'
  CHAT_ARTIFACT_BLOB_ENDPOINT: blobEndpoint
  CHAT_ARTIFACT_CONTAINER: blobContainer
  CHAT_MEMORY_SEARCH_ENDPOINT: searchEndpoint
  CHAT_MEMORY_SEARCH_INDEX: memoryIndexName
  CHAT_MEMORY_AUTO_SETUP: 'true'
  PE_FEATURE_CHAT_MEMORY: 'true'
}

resource history 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'chat-history' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identityId}': {} }
  }
  properties: {
    managedEnvironmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8080
        allowInsecure: false
        transport: 'http'
      }
      registries: [{ server: registryServer, identity: identityId }]
    }
    template: {
      containers: [{
        name: 'history'
        image: image
        command: ['python', '-m', 'uvicorn', 'chat_history_app:app', '--host', '0.0.0.0', '--port', '8080']
        env: [for setting in items(settings): { name: setting.key, value: setting.value }]
        resources: { cpu: json('0.5'), memory: '1Gi' }
        probes: [
          { type: 'Startup', httpGet: { path: '/api/health', port: 8080 }, periodSeconds: 10, failureThreshold: 30 }
          { type: 'Readiness', httpGet: { path: '/api/health', port: 8080 }, periodSeconds: 10, failureThreshold: 3 }
          { type: 'Liveness', httpGet: { path: '/api/health', port: 8080 }, periodSeconds: 30, failureThreshold: 3 }
        ]
      }]
      scale: { minReplicas: 1, maxReplicas: 2 }
    }
  }
}

@description('Authenticated history origin.')
output url string = 'https://${history.properties.configuration.ingress.fqdn}'
@description('History Container App name.')
output name string = history.name
