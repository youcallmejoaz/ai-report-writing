// Least-privilege data-plane role assignments for the application's managed identity.
param principalId string
param storageAccountName string
param openAiName string
param docIntelName string
param serviceBusName string

var roles = {
  blobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  openAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  cognitiveServicesUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'
  serviceBusDataOwner: '090c5cfd-751d-490a-894a-3ce6f1109419'
}

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' existing = { name: storageAccountName }
resource aoai 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = { name: openAiName }
resource di 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = { name: docIntelName }
resource sb 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' existing = { name: serviceBusName }

resource raBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: sa
  name: guid(sa.id, principalId, roles.blobDataContributor)
  properties: { principalId: principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobDataContributor) }
}

resource raAoai 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aoai
  name: guid(aoai.id, principalId, roles.openAiUser)
  properties: { principalId: principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.openAiUser) }
}

resource raDi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: di
  name: guid(di.id, principalId, roles.cognitiveServicesUser)
  properties: { principalId: principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesUser) }
}

resource raSb 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: sb
  name: guid(sb.id, principalId, roles.serviceBusDataOwner)
  properties: { principalId: principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.serviceBusDataOwner) }
}
