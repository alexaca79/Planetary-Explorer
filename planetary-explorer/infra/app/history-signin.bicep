metadata name = 'Optional History Sign-in'
metadata description = 'Enables tenant-specific user sign-in without blocking anonymous public map access.'

@description('Existing frontend App Service name.')
param webAppName string
@description('Microsoft Entra tenant ID.')
param tenantId string
@description('Application client ID for this frontend and history API.')
param clientId string
@description('Existing App Service setting holding the confidential-client secret.')
param credentialSettingName string = 'HISTORY_AUTH_CLIENT_SECRET'

resource web 'Microsoft.Web/sites@2023-12-01' existing = { name: webAppName }
resource auth 'Microsoft.Web/sites/config@2023-12-01' = {
  parent: web
  name: 'authsettingsV2'
  properties: {
    platform: { enabled: true, runtimeVersion: '~1' }
    globalValidation: { requireAuthentication: false, unauthenticatedClientAction: 'AllowAnonymous' }
    httpSettings: { requireHttps: true }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: clientId
          openIdIssuer: '${environment().authentication.loginEndpoint}${tenantId}/v2.0'
          clientSecretSettingName: credentialSettingName
        }
        validation: { allowedAudiences: [clientId, 'api://${clientId}'] }
      }
    }
    login: {
      tokenStore: { enabled: true }
      preserveUrlFragmentsForLogins: true
    }
  }
}
