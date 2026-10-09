// PostgreSQL Flexible Server: private access only, Entra ID auth only, CMK, zone-redundant HA.
param location string
param prefix string
param tags object
param subnetId string
param privateDnsZoneId string
param cmkIdentityId string
param keyUriWithVersion string
param tenantId string
param workspaceId string
param skuName string = 'Standard_D4ds_v5'

resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2022-12-01' = {
  name: '${prefix}-pg'
  location: location
  tags: tags
  sku: { name: skuName, tier: 'GeneralPurpose' }
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${cmkIdentityId}': {} } }
  properties: {
    version: '16'
    storage: { storageSizeGB: 128 }
    network: { delegatedSubnetResourceId: subnetId, privateDnsZoneArmResourceId: privateDnsZoneId }
    highAvailability: { mode: 'ZoneRedundant' }
    // Geo-redundant backup with CMK additionally needs a key + identity in UK West; added in build phase.
    backup: { backupRetentionDays: 35, geoRedundantBackup: 'Disabled' }
    authConfig: { activeDirectoryAuth: 'Enabled', passwordAuth: 'Disabled', tenantId: tenantId }
    dataEncryption: {
      type: 'AzureKeyVault'
      primaryKeyURI: keyUriWithVersion
      primaryUserAssignedIdentityId: cmkIdentityId
    }
  }
}

resource tls 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2022-12-01' = {
  parent: pg
  name: 'ssl_min_protocol_version'
  properties: { value: 'TLSv1.2', source: 'user-override' }
}

resource diag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: pg
  name: 'to-law'
  properties: {
    workspaceId: workspaceId
    logs: [{ categoryGroup: 'allLogs', enabled: true }]
  }
}

output fqdn string = pg.properties.fullyQualifiedDomainName
