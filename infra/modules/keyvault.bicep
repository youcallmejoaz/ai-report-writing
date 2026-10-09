// Key Vault Premium (HSM-backed keys) holding the customer-managed keys for Storage and PostgreSQL.
param location string
param prefix string
param tags object
param tenantId string
param workspaceId string

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${prefix}-kv'
  location: location
  tags: tags
  properties: {
    tenantId: tenantId
    sku: { family: 'A', name: 'premium' }
    enableRbacAuthorization: true
    enablePurgeProtection: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
  }
}

resource cmk 'Microsoft.KeyVault/vaults/keys@2023-07-01' = {
  parent: kv
  name: 'data-cmk'
  properties: {
    kty: 'RSA-HSM'
    keySize: 3072
    rotationPolicy: {
      attributes: { expiryTime: 'P2Y' }
      lifetimeActions: [{ action: { type: 'rotate' }, trigger: { timeBeforeExpiry: 'P60D' } }]
    }
  }
}

resource diag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: kv
  name: 'to-law'
  properties: {
    workspaceId: workspaceId
    logs: [{ categoryGroup: 'audit', enabled: true }]
  }
}

output id string = kv.id
output name string = kv.name
output uri string = kv.properties.vaultUri
output keyName string = cmk.name
output keyUri string = cmk.properties.keyUri
output keyUriWithVersion string = cmk.properties.keyUriWithVersion
