metadata name = 'Planetary Explorer GeoFM'
metadata description = 'Deploys an internal MCP control plane and a queue-scaled PlanAura GPU worker.'

@description('Resource name for the internal GeoFM MCP Container App.')
param name string

@description('Resource name for the GeoFM GPU worker Container App.')
param workerName string

@description('Azure region for the Container Apps resources.')
param location string = resourceGroup().location

@description('Tags applied to all GeoFM resources.')
param tags object = {}

@description('Name of the existing Container Apps managed environment.')
param containerAppsEnvironmentName string

@description('Name of the existing Azure Container Registry.')
param containerRegistryName string

@description('Name of the existing Storage account used for durable runs.')
param storageAccountName string

@description('Blob service endpoint for the durable GeoFM repository.')
param storageBlobEndpoint string

@description('Queue service endpoint for GeoFM work dispatch.')
param storageQueueEndpoint string

@description('Friendly GPU workload profile name declared on the managed environment.')
param gpuWorkloadProfileName string = 'geofm-gpu'

@description('Allow the conditional PlanAura profile after operator validation.')
param isConditionalModelAllowed bool = false

@description('Expose the API-key-protected MCP endpoint outside its Container Apps environment.')
param mcpExternalIngress bool = false

@secure()
@minLength(32)
@description('Shared API key required by the internal GeoFM MCP endpoint.')
param mcpApiKey string

@secure()
@minLength(32)
@description('HMAC key used to verify backend-signed GeoFM run ownership.')
param ownerSigningKey string

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-10-02-preview' existing = {
  name: containerAppsEnvironmentName
}

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: containerRegistryName
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}

resource controlIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${name}'
  location: location
  tags: tags
}

resource workerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${workerName}'
  location: location
  tags: tags
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' existing = {
  parent: storageAccount
  name: 'default'
}

resource geoFmContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' existing = {
  parent: blobService
  name: 'geofm'
}

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-01-01' existing = {
  parent: storageAccount
  name: 'default'
}

resource geoFmQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-01-01' existing = {
  parent: queueService
  name: 'geofm-jobs'
}

resource geoFmPoisonQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-01-01' existing = {
  parent: queueService
  name: 'geofm-poison'
}

resource controlAcrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(controlIdentity.id, containerRegistry.id, 'AcrPull')
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d'
    )
    principalId: controlIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource workerAcrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workerIdentity.id, containerRegistry.id, 'AcrPull')
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d'
    )
    principalId: workerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource controlBlobDataRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(controlIdentity.id, geoFmContainer.id, 'StorageBlobDataContributor')
  scope: geoFmContainer
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
    )
    principalId: controlIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource controlBlobDelegatorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(controlIdentity.id, storageAccount.id, 'StorageBlobDelegator')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'db58b8e5-c6ad-4a2a-8342-4190687cbf4a'
    )
    principalId: controlIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource workerBlobDataRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workerIdentity.id, geoFmContainer.id, 'StorageBlobDataContributor')
  scope: geoFmContainer
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
    )
    principalId: workerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource controlQueueSenderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(controlIdentity.id, geoFmQueue.id, 'StorageQueueDataMessageSender')
  scope: geoFmQueue
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'c6a89b2d-59bc-44d0-9896-0f6e12d7b80a'
    )
    principalId: controlIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource controlQueueReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(controlIdentity.id, geoFmQueue.id, 'StorageQueueDataReader')
  scope: geoFmQueue
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '19e7f393-937e-4f77-808e-94535e297925'
    )
    principalId: controlIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource controlPoisonQueueReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(controlIdentity.id, geoFmPoisonQueue.id, 'StorageQueueDataReader')
  scope: geoFmPoisonQueue
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '19e7f393-937e-4f77-808e-94535e297925'
    )
    principalId: controlIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource workerQueueDataRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workerIdentity.id, geoFmQueue.id, 'StorageQueueDataContributor')
  scope: geoFmQueue
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
    )
    principalId: workerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource workerPoisonQueueDataRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workerIdentity.id, geoFmPoisonQueue.id, 'StorageQueueDataContributor')
  scope: geoFmPoisonQueue
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
    )
    principalId: workerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource mcpApp 'Microsoft.App/containerApps@2025-01-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'geofm' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${controlIdentity.id}': {}
    }
  }
  dependsOn: [
    controlAcrPullRole
    controlBlobDataRole
    controlBlobDelegatorRole
    controlQueueSenderRole
    controlQueueReaderRole
    controlPoisonQueueReaderRole
  ]
  properties: {
    environmentId: containerAppsEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: mcpExternalIngress
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
      registries: [
        {
          server: containerRegistry.properties.loginServer
          identity: controlIdentity.id
        }
      ]
      secrets: concat(
        !empty(mcpApiKey) ? [
          {
            name: 'geofm-mcp-api-key'
            value: mcpApiKey
          }
        ] : [],
        !empty(ownerSigningKey) ? [
          {
            name: 'geofm-owner-signing-key'
            value: ownerSigningKey
          }
        ] : []
      )
    }
    template: {
      containers: [
        {
          name: 'geofm'
          image: 'mcr.microsoft.com/dotnet/samples:aspnetapp'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: concat([
            {
              name: 'PORT'
              value: '8080'
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: controlIdentity.properties.clientId
            }
            {
              name: 'AZURE_STORAGE_BLOB_ENDPOINT'
              value: storageBlobEndpoint
            }
            {
              name: 'AZURE_STORAGE_QUEUE_ENDPOINT'
              value: storageQueueEndpoint
            }
            {
              name: 'GEOFM_CONTAINER_NAME'
              value: 'geofm'
            }
            {
              name: 'GEOFM_QUEUE_NAME'
              value: 'geofm-jobs'
            }
            {
              name: 'GEOFM_ALLOW_CONDITIONAL'
              value: isConditionalModelAllowed ? 'true' : 'false'
            }
            {
              name: 'GEOFM_REQUIRE_API_KEY'
              value: 'true'
            }
          ], !empty(mcpApiKey) ? [
            {
              name: 'GEOFM_MCP_API_KEY'
              secretRef: 'geofm-mcp-api-key'
            }
          ] : [], !empty(ownerSigningKey) ? [
            {
              name: 'GEOFM_OWNER_SIGNING_KEY'
              secretRef: 'geofm-owner-signing-key'
            }
          ] : [])
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
      }
    }
  }
}

resource workerApp 'Microsoft.App/containerApps@2025-01-01' = {
  name: workerName
  location: location
  tags: union(tags, { 'azd-service-name': 'geofm-worker' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${workerIdentity.id}': {}
    }
  }
  dependsOn: [
    workerAcrPullRole
    workerBlobDataRole
    workerQueueDataRole
    workerPoisonQueueDataRole
  ]
  properties: {
    environmentId: containerAppsEnvironment.id
    workloadProfileName: gpuWorkloadProfileName
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [
        {
          server: containerRegistry.properties.loginServer
          identity: workerIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'geofm-worker'
          image: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          resources: {
            cpu: 8
            memory: '56Gi'
          }
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: workerIdentity.properties.clientId
            }
            {
              name: 'AZURE_STORAGE_BLOB_ENDPOINT'
              value: storageBlobEndpoint
            }
            {
              name: 'AZURE_STORAGE_QUEUE_ENDPOINT'
              value: storageQueueEndpoint
            }
            {
              name: 'GEOFM_CONTAINER_NAME'
              value: 'geofm'
            }
            {
              name: 'GEOFM_QUEUE_NAME'
              value: 'geofm-jobs'
            }
            {
              name: 'GEOFM_POISON_QUEUE_NAME'
              value: 'geofm-poison'
            }
            {
              name: 'GEOFM_AUTOCAST_FLOAT16'
              value: 'true'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
        pollingInterval: 30
        cooldownPeriod: 300
        rules: [
          {
            name: 'geofm-queue'
            azureQueue: {
              accountName: storageAccount.name
              queueName: 'geofm-jobs'
              queueLength: 1
              identity: workerIdentity.id
            }
          }
        ]
      }
      terminationGracePeriodSeconds: 60
    }
  }
}

@description('Name of the GeoFM MCP Container App.')
output mcpName string = mcpApp.name

@description('Internal HTTPS endpoint for the GeoFM MCP service.')
output mcpUri string = 'https://${mcpApp.properties.configuration.ingress.fqdn}'

@description('Name of the queue-scaled GeoFM GPU worker.')
output workerName string = workerApp.name

@description('Client ID of the GeoFM control-plane managed identity.')
output controlIdentityClientId string = controlIdentity.properties.clientId

@description('Client ID of the GeoFM worker managed identity.')
output workerIdentityClientId string = workerIdentity.properties.clientId
