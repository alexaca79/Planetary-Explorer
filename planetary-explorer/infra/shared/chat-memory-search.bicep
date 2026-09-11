metadata name = 'Private Chat Memory Search'
metadata description = 'Dedicated keyless AI Search service for owner-filtered chat recall.'

@description('Globally unique name of the dedicated memory Search service.')
param name string

@description('Azure region for the Search service.')
param location string

@description('Tags applied to the Search service.')
param tags object

@description('Disable the public endpoint when using private networking.')
param enablePrivateEndpoints bool

@description('Search tier for the memory index.')
@allowed(['basic', 'standard'])
param skuName string = 'basic'

@description('Cloud environment used to construct the Search endpoint.')
@allowed(['Commercial', 'Government'])
param cloudEnvironment string = 'Commercial'

resource search 'Microsoft.Search/searchServices@2025-05-01' = {
  name: name
  location: location
  tags: tags
  sku: { name: skuName }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'Default'
    disableLocalAuth: true
    publicNetworkAccess: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
    semanticSearch: 'free'
  }
}

@description('Search service name.')
output name string = search.name

@description('Search service ARM resource ID.')
output id string = search.id

@description('Keyless Search endpoint.')
output endpoint string = 'https://${search.name}.search.${cloudEnvironment == 'Government' ? 'azure.us' : 'windows.net'}'
