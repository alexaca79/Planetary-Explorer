metadata name = 'Chat History Cosmos DB'
metadata description = 'Deploys a serverless Cosmos DB for user-partitioned chat history.'

@description('Name of the Azure Cosmos DB account.')
param name string

@description('Azure region for the Cosmos DB account.')
param location string = resourceGroup().location

@description('Resource tags applied to the Cosmos DB account.')
param tags object = {}

@description('Name of the Cosmos DB for NoSQL database.')
param databaseName string = 'planetary-explorer'

@description('Name of the user-partitioned chat history container.')
param containerName string = 'chat-history'

@description('Number of days saved chat sessions remain available.')
@minValue(1)
param retentionDays int = 90

@description('Disable public network access when private endpoints are enabled.')
param enablePrivateEndpoints bool = false

resource account 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: name
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    disableKeyBasedMetadataWriteAccess: true
    disableLocalAuth: true
    enableAutomaticFailover: false
    enableMultipleWriteLocations: false
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    minimalTlsVersion: 'Tls12'
    networkAclBypass: 'AzureServices'
    publicNetworkAccess: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: account
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
  }
}

resource historyContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: database
  name: containerName
  properties: {
    resource: {
      id: containerName
      defaultTtl: retentionDays * 86400
      partitionKey: {
        paths: [
          '/ownerId'
        ]
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        automatic: true
        indexingMode: 'consistent'
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/messages/*'
          }
          {
            path: '/context/*'
          }
          {
            path: '/attachments/*'
          }
        ]
      }
    }
  }
}

@description('Name of the deployed Cosmos DB account.')
output accountName string = account.name

@description('Resource ID of the deployed Cosmos DB account.')
output accountId string = account.id

@description('Keyless Cosmos DB for NoSQL endpoint used by the API.')
output endpoint string = account.properties.documentEndpoint

@description('Name of the chat history database.')
output databaseName string = database.name

@description('Name of the chat history container.')
output containerName string = historyContainer.name