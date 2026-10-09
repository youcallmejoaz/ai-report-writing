// Azure OpenAI (Standard regional deployment, pinned model version) and Document Intelligence, UK South,
// private endpoints only, Entra ID auth only.
param location string
param prefix string
param tags object
param peSubnetId string
param openAiDnsZoneId string
param cognitiveDnsZoneId string
param workspaceId string
@description('Model and version confirmed available as a Standard (regional) deployment in UK South at build time.')
param chatModelName string
param chatModelVersion string
param chatCapacityK int = 50

resource aoai 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: '${prefix}-aoai'
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: '${prefix}-aoai'
    publicNetworkAccess: 'Disabled'
    disableLocalAuth: true
    networkAcls: { defaultAction: 'Deny' }
  }
}

resource chat 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: aoai
  name: 'report-drafting'
  sku: { name: 'Standard', capacity: chatCapacityK } // regional processing; Global/DataZone denied by policy
  properties: {
    model: { format: 'OpenAI', name: chatModelName, version: chatModelVersion }
    versionUpgradeOption: 'NoAutoUpgrade' // model changes go through re-evaluation, never automatic
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

resource docintel 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: '${prefix}-docintel'
  location: location
  tags: tags
  kind: 'FormRecognizer'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: '${prefix}-docintel'
    publicNetworkAccess: 'Disabled'
    disableLocalAuth: true
    networkAcls: { defaultAction: 'Deny' }
  }
}

module peAoai 'private-endpoint.bicep' = {
  name: 'pe-aoai'
  params: {
    location: location
    name: '${prefix}-pe-aoai'
    subnetId: peSubnetId
    targetId: aoai.id
    groupId: 'account'
    dnsZoneId: openAiDnsZoneId
    tags: tags
  }
}

module peDocintel 'private-endpoint.bicep' = {
  name: 'pe-docintel'
  params: {
    location: location
    name: '${prefix}-pe-docintel'
    subnetId: peSubnetId
    targetId: docintel.id
    groupId: 'account'
    dnsZoneId: cognitiveDnsZoneId
    tags: tags
  }
}

resource diagAoai 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: aoai
  name: 'to-law'
  properties: {
    workspaceId: workspaceId
    logs: [{ categoryGroup: 'audit', enabled: true }]
    metrics: [{ category: 'AllMetrics', enabled: true }]
  }
}

output openAiId string = aoai.id
output openAiEndpoint string = aoai.properties.endpoint
output deploymentName string = chat.name
output docIntelId string = docintel.id
output docIntelEndpoint string = docintel.properties.endpoint
