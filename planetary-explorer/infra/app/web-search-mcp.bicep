metadata name = 'Planetary Explorer Web Search MCP'
metadata description = 'Deploys an internal MCP service backed by Microsoft Foundry Web Search.'

@description('Resource name for the Web Search MCP Container App.')
param name string

@description('Azure region for the Container App.')
param location string = resourceGroup().location

@description('Tags applied to the Web Search MCP Container App.')
param tags object = {}

@description('Name of the existing Container Apps managed environment.')
param containerAppsEnvironmentName string

@description('Name of the existing Azure Container Registry.')
param containerRegistryName string

@description('Microsoft Foundry project endpoint used for Responses API calls.')
param foundryProjectEndpoint string

@description('Existing Azure OpenAI deployment used to synthesize grounded search results.')
param modelDeploymentName string

@secure()
@description('Shared API key required on Web Search MCP data-plane requests.')
param apiKey string

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-10-02-preview' existing = {
  name: containerAppsEnvironmentName
}

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: containerRegistryName
}

resource app 'Microsoft.App/containerApps@2025-01-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'web-search-mcp' })
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    environmentId: containerAppsEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: [
        {
          name: 'web-search-mcp-api-key'
          value: apiKey
        }
      ]
      registries: [
        {
          server: containerRegistry.properties.loginServer
          identity: 'system'
        }
      ]
      ingress: {
        external: false
        targetPort: 8080
        allowInsecure: false
        transport: 'http'
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
    }
    template: {
      containers: [
        {
          name: 'web-search-mcp'
          image: 'mcr.microsoft.com/dotnet/samples:aspnetapp'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'PORT'
              value: '8080'
            }
            {
              name: 'FOUNDRY_PROJECT_ENDPOINT'
              value: foundryProjectEndpoint
            }
            {
              name: 'FOUNDRY_MODEL'
              value: modelDeploymentName
            }
            {
              name: 'WEB_SEARCH_MCP_API_KEY'
              secretRef: 'web-search-mcp-api-key'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
        rules: [
          {
            name: 'http-concurrency'
            http: {
              metadata: {
                concurrentRequests: '5'
              }
            }
          }
        ]
      }
    }
  }
}

resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(app.id, containerRegistry.id, 'AcrPull')
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d'
    )
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

@description('Resource name of the Web Search MCP Container App.')
output name string = app.name

@description('Internal HTTPS endpoint of the Web Search MCP Container App.')
output uri string = 'https://${app.properties.configuration.ingress.fqdn}'

@description('System-assigned managed identity principal ID.')
output principalId string = app.identity.principalId