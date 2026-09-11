metadata name = 'History Private Endpoints'
metadata description = 'Adds private data endpoints to an existing VNet without changing its subnets.'

@description('Location of the existing virtual network.')
param location string
@description('Existing virtual network name.')
param vnetName string
@description('Existing subnet for private endpoints.')
param subnetName string
@description('Cosmos DB account resource ID.')
param cosmosAccountId string
@description('Blob Storage account resource ID.')
param storageAccountId string
@description('Dedicated memory Search service resource ID.')
param searchServiceId string
@description('Unique resource name suffix.')
param suffix string
@description('Tags for new resources.')
param tags object

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
}
resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: vnet
  name: subnetName
}
resource blobDns 'Microsoft.Network/privateDnsZones@2024-06-01' existing = {
  name: 'privatelink.blob.${environment().suffixes.storage}'
}
resource searchDns 'Microsoft.Network/privateDnsZones@2024-06-01' existing = {
  name: 'privatelink.search.windows.net'
}
resource cosmosDns 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.documents.azure.com'
  location: 'global'
  tags: tags
}
resource cosmosDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: cosmosDns
  name: 'link-history-${suffix}'
  location: 'global'
  properties: {
    virtualNetwork: { id: vnet.id }
    registrationEnabled: false
  }
}

var endpoints = [
  { name: 'cosmos', resourceId: cosmosAccountId, groupId: 'Sql', dnsZoneId: cosmosDns.id }
  { name: 'blob', resourceId: storageAccountId, groupId: 'blob', dnsZoneId: blobDns.id }
  { name: 'search', resourceId: searchServiceId, groupId: 'searchService', dnsZoneId: searchDns.id }
]

module privateEndpoints './private-endpoint.bicep' = [for endpoint in endpoints: {
  name: 'history-pe-${endpoint.name}-${suffix}'
  params: {
    name: 'pe-history-${endpoint.name}-${suffix}'
    location: location
    tags: tags
    serviceResourceId: endpoint.resourceId
    groupId: endpoint.groupId
    subnetId: subnet.id
    privateDnsZoneId: endpoint.dnsZoneId
  }
}]
