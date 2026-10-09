// Documents, renditions and outputs; immutable containers for the audit archive and final reports.
param location string
param prefix string
param tags object
param cmkIdentityId string
param keyVaultUri string
param keyName string
param workspaceId string
@description('WORM retention for final reports and audit archive, in days. Align with the firm\'s retention schedule.')
param wormRetentionDays int = 2555

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: toLower(replace('${prefix}docs', '-', ''))
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_GZRS' } // zone-redundant in UK South, geo-replicated to UK West
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${cmkIdentityId}': {} } }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false // Entra ID auth only; no account keys or SAS
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
    encryption: {
      keySource: 'Microsoft.Keyvault'
      identity: { userAssignedIdentity: cmkIdentityId }
      keyvaultproperties: { keyvaulturi: keyVaultUri, keyname: keyName }
      requireInfrastructureEncryption: true
      services: { blob: { enabled: true, keyType: 'Account' } }
    }
  }
}

resource blob 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: sa
  name: 'default'
  properties: {
    isVersioningEnabled: true
    deleteRetentionPolicy: { enabled: true, days: 30 }
    containerDeleteRetentionPolicy: { enabled: true, days: 30 }
  }
}

var workingContainers = ['documents', 'renditions', 'drafts']
resource ctr 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for c in workingContainers: {
  parent: blob
  name: c
  properties: { publicAccess: 'None' }
}]

resource finalReports 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blob
  name: 'final-reports'
  properties: { publicAccess: 'None' }
}

resource auditArchive 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blob
  name: 'audit-archive'
  properties: { publicAccess: 'None' }
}

// Time-based retention. Left unlocked so the policy can be tested; locking is a deliberate,
// irreversible step taken after compliance sign-off.
resource wormFinal 'Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies@2023-05-01' = {
  parent: finalReports
  name: 'default'
  properties: { immutabilityPeriodSinceCreationInDays: wormRetentionDays, allowProtectedAppendWrites: false }
}

resource wormAudit 'Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies@2023-05-01' = {
  parent: auditArchive
  name: 'default'
  properties: { immutabilityPeriodSinceCreationInDays: wormRetentionDays, allowProtectedAppendWrites: true }
}

resource diag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: blob
  name: 'to-law'
  properties: {
    workspaceId: workspaceId
    logs: [{ categoryGroup: 'audit', enabled: true }]
  }
}

output id string = sa.id
output name string = sa.name
