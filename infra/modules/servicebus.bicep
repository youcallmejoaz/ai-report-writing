// Queues between pipeline stages. Premium tier is required for private endpoints.
param location string
param prefix string
param tags object

resource ns 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' = {
  name: '${prefix}-sb'
  location: location
  tags: tags
  sku: { name: 'Premium', tier: 'Premium', capacity: 1 }
  properties: {
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
    minimumTlsVersion: '1.2'
  }
}

var queues = ['ingest', 'extract', 'evidence', 'draft', 'verify', 'assemble']
resource q 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = [for name in queues: {
  parent: ns
  name: name
  properties: {
    maxDeliveryCount: 5
    deadLetteringOnMessageExpiration: true
    lockDuration: 'PT5M'
    defaultMessageTimeToLive: 'P1D'
  }
}]

output id string = ns.id
output name string = ns.name
