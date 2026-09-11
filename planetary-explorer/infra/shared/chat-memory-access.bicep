metadata name = 'Chat Memory Search Access'
metadata description = 'Grants a history identity data and schema access to its dedicated Search service.'

@description('Name of the dedicated chat memory Search service.')
param searchServiceName string

@description('Object ID of the identity operating the memory store.')
param principalId string

resource search 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchServiceName
}

var roleIds = [
  '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
]

resource roles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in roleIds: {
  name: guid(search.id, principalId, roleId)
  scope: search
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
  }
}]
