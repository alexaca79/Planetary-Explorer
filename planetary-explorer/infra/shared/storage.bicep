param location string = resourceGroup().location
param tags object = {}

param name string
param sku object = {
  name: 'Standard_LRS'
}

@description('Enable private endpoints — disables public access')
param enablePrivateEndpoints bool = false

@description('Create the private Blob container and Queue used by durable GeoFM runs.')
param deployGeoFmResources bool = false

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: name
  location: location
  tags: tags
  sku: sku
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
    networkAcls: {
      defaultAction: enablePrivateEndpoints ? 'Deny' : 'Allow'
      bypass: 'AzureServices'
    }
  }
}

// Create blob container for application data
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

resource dataContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'planetary-explorer-data'
  properties: {
    publicAccess: 'None'
  }
}

resource geoFmContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = if (deployGeoFmResources) {
  parent: blobService
  name: 'geofm'
  properties: {
    publicAccess: 'None'
  }
}

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-01-01' = if (deployGeoFmResources) {
  parent: storageAccount
  name: 'default'
}

resource geoFmQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-01-01' = if (deployGeoFmResources) {
  parent: queueService
  name: 'geofm-jobs'
}

output name string = storageAccount.name
output id string = storageAccount.id
output primaryEndpoints object = storageAccount.properties.primaryEndpoints
output blobEndpoint string = storageAccount.properties.primaryEndpoints.blob
output queueEndpoint string = storageAccount.properties.primaryEndpoints.queue
output geoFmContainerName string = deployGeoFmResources ? geoFmContainer.name : ''
output geoFmQueueName string = deployGeoFmResources ? geoFmQueue.name : ''
