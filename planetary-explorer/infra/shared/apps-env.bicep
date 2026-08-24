// Container Apps Environment — VNet integration must be set at creation time
param name string
param location string = resourceGroup().location
param tags object = {}

param logAnalyticsWorkspaceName string

@description('Subnet ID for VNet integration (required when using private endpoints)')
param infrastructureSubnetId string = ''

@description('Whether the Container Apps Environment uses internal-only ingress (no public IP)')
param internal bool = false

@description('Add a scale-to-zero serverless GPU workload profile for GeoFM inference.')
param enableGeoFmGpu bool = false

@description('Friendly workload profile name selected by the GeoFM worker Container App.')
param geoFmGpuProfileName string = 'geofm-gpu'

@description('Region-supported serverless GPU profile type. Validate with az containerapp env workload-profile list-supported before deployment.')
param geoFmGpuProfileType string = 'Consumption-GPU-NC8as-T4'

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' existing = {
  name: logAnalyticsWorkspaceName
}

resource appsEnv 'Microsoft.App/managedEnvironments@2024-10-02-preview' = {
  name: name
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsWorkspace.properties.customerId
        sharedKey: logAnalyticsWorkspace.listKeys().primarySharedKey
      }
    }
    // VNet integration must be set at creation time — cannot be added later.
    // When infrastructureSubnetId is provided, the CAE joins the VNet so it can
    // reach private-endpoint-locked services (ACR, AI Services, Key Vault, etc.).
    vnetConfiguration: !empty(infrastructureSubnetId) ? {
      infrastructureSubnetId: infrastructureSubnetId
      internal: internal
    } : null
    workloadProfiles: concat([
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ], enableGeoFmGpu ? [
      {
        name: geoFmGpuProfileName
        workloadProfileType: geoFmGpuProfileType
      }
    ] : [])
  }
}

output name string = appsEnv.name
output domain string = appsEnv.properties.defaultDomain
