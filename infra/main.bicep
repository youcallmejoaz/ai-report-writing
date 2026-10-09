// Production landing zone for the report-writing application, UK South.
// Deploy:  az deployment group create -g <rg> -f main.bicep -p main.bicepparam
//          az deployment sub create -l uksouth -f modules/policy.bicep   (once per subscription)

@allowed(['uksouth'])
param location string = 'uksouth'
@minLength(3)
@maxLength(12)
param prefix string
param tenantId string = tenant().tenantId
param registryServer string
param apiImage string
param workerImage string
param chatModelName string
param chatModelVersion string
#disable-next-line secure-secrets-in-params // a Key Vault secret URI, not the secret itself
param tlsCertSecretId string
param entraApiAudience string

var tags = {
  workload: 'ai-report-writing'
  dataClassification: 'Confidential-PersonalFinancial'
  dataResidency: 'UK'
}

resource appIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-id-app'
  location: location
  tags: tags
}

resource cmkIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-id-cmk'
  location: location
  tags: tags
}

resource gwIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-id-agw'
  location: location
  tags: tags
}

module network 'modules/network.bicep' = {
  name: 'network'
  params: { location: location, prefix: prefix, tags: tags }
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: { location: location, prefix: prefix, tags: tags }
}

module kv 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: { location: location, prefix: prefix, tags: tags, tenantId: tenantId, workspaceId: monitoring.outputs.workspaceId }
}

// The CMK identity may only wrap/unwrap with the data key; the gateway identity may only read the TLS cert.
resource kvRef 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: '${prefix}-kv'
}

resource cmkRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kvRef
  name: guid(prefix, cmkIdentity.id, 'kv-crypto-service-encryption-user')
  properties: {
    principalId: cmkIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'e147488a-f6f5-4113-8e2d-b22465e65bf6')
  }
  dependsOn: [kv]
}

resource gwSecretRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kvRef
  name: guid(prefix, gwIdentity.id, 'kv-secrets-user')
  properties: {
    principalId: gwIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
  dependsOn: [kv]
}

module peKv 'modules/private-endpoint.bicep' = {
  name: 'pe-kv'
  params: {
    location: location
    name: '${prefix}-pe-kv'
    subnetId: network.outputs.peSubnetId
    targetId: kv.outputs.id
    groupId: 'vault'
    dnsZoneId: network.outputs.dnsZoneIds.vault
    tags: tags
  }
}

module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    location: location
    prefix: prefix
    tags: tags
    cmkIdentityId: cmkIdentity.id
    keyVaultUri: kv.outputs.uri
    keyName: kv.outputs.keyName
    workspaceId: monitoring.outputs.workspaceId
  }
  dependsOn: [cmkRole, peKv]
}

module peBlob 'modules/private-endpoint.bicep' = {
  name: 'pe-blob'
  params: {
    location: location
    name: '${prefix}-pe-blob'
    subnetId: network.outputs.peSubnetId
    targetId: storage.outputs.id
    groupId: 'blob'
    dnsZoneId: network.outputs.dnsZoneIds.blob
    tags: tags
  }
}

module postgres 'modules/postgres.bicep' = {
  name: 'postgres'
  params: {
    location: location
    prefix: prefix
    tags: tags
    subnetId: network.outputs.postgresSubnetId
    privateDnsZoneId: network.outputs.dnsZoneIds.postgres
    cmkIdentityId: cmkIdentity.id
    keyUriWithVersion: kv.outputs.keyUriWithVersion
    tenantId: tenantId
    workspaceId: monitoring.outputs.workspaceId
  }
  dependsOn: [cmkRole, peKv]
}

module ai 'modules/ai.bicep' = {
  name: 'ai'
  params: {
    location: location
    prefix: prefix
    tags: tags
    peSubnetId: network.outputs.peSubnetId
    openAiDnsZoneId: network.outputs.dnsZoneIds.openai
    cognitiveDnsZoneId: network.outputs.dnsZoneIds.cognitive
    workspaceId: monitoring.outputs.workspaceId
    chatModelName: chatModelName
    chatModelVersion: chatModelVersion
  }
}

module servicebus 'modules/servicebus.bicep' = {
  name: 'servicebus'
  params: { location: location, prefix: prefix, tags: tags }
}

module peSb 'modules/private-endpoint.bicep' = {
  name: 'pe-sb'
  params: {
    location: location
    name: '${prefix}-pe-sb'
    subnetId: network.outputs.peSubnetId
    targetId: servicebus.outputs.id
    groupId: 'namespace'
    dnsZoneId: network.outputs.dnsZoneIds.servicebus
    tags: tags
  }
}

module roles 'modules/roles.bicep' = {
  name: 'roles'
  params: {
    principalId: appIdentity.properties.principalId
    storageAccountName: storage.outputs.name
    openAiName: '${prefix}-aoai'
    docIntelName: '${prefix}-docintel'
    serviceBusName: servicebus.outputs.name
  }
  dependsOn: [ai]
}

module apps 'modules/apps.bicep' = {
  name: 'apps'
  params: {
    location: location
    prefix: prefix
    tags: tags
    subnetId: network.outputs.appsSubnetId
    workspaceId: monitoring.outputs.workspaceId
    appIdentityId: appIdentity.id
    appIdentityClientId: appIdentity.properties.clientId
    registryServer: registryServer
    apiImage: apiImage
    workerImage: workerImage
    env: [
      { name: 'AZURE_OPENAI_ENDPOINT', value: ai.outputs.openAiEndpoint }
      { name: 'AZURE_OPENAI_DEPLOYMENT', value: ai.outputs.deploymentName }
      { name: 'DOCUMENT_INTELLIGENCE_ENDPOINT', value: ai.outputs.docIntelEndpoint }
      { name: 'POSTGRES_HOST', value: postgres.outputs.fqdn }
      { name: 'STORAGE_ACCOUNT', value: storage.outputs.name }
      { name: 'SERVICEBUS_NAMESPACE', value: '${servicebus.outputs.name}.servicebus.windows.net' }
      { name: 'ENTRA_TENANT_ID', value: tenantId }
      { name: 'ENTRA_API_AUDIENCE', value: entraApiAudience }
      { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: monitoring.outputs.appInsightsConnectionString }
    ]
  }
  dependsOn: [roles]
}

module gateway 'modules/appgateway.bicep' = {
  name: 'gateway'
  params: {
    location: location
    prefix: prefix
    tags: tags
    subnetId: network.outputs.appGwSubnetId
    backendFqdn: apps.outputs.apiFqdn
    tlsCertSecretId: tlsCertSecretId
    gatewayIdentityId: gwIdentity.id
  }
  dependsOn: [gwSecretRole]
}
