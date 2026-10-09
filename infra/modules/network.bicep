// VNet with subnets for ingress (App Gateway), Container Apps, PostgreSQL (delegated) and private endpoints,
// plus the private DNS zones that make PaaS endpoints resolve to private IPs.
param location string
param prefix string
param tags object

var zones = [
  'privatelink.blob.${environment().suffixes.storage}'
  'privatelink.vaultcore.azure.net'
  'privatelink.openai.azure.com'
  'privatelink.cognitiveservices.azure.com'
  'privatelink.servicebus.windows.net'
  'privatelink.postgres.database.azure.com'
]

resource nsgPe 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: '${prefix}-nsg-pe'
  location: location
  tags: tags
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: '${prefix}-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: ['10.40.0.0/16'] }
    subnets: [
      { name: 'snet-appgw', properties: { addressPrefix: '10.40.0.0/24' } }
      {
        name: 'snet-apps'
        properties: {
          addressPrefix: '10.40.2.0/23'
          delegations: [{ name: 'aca', properties: { serviceName: 'Microsoft.App/environments' } }]
        }
      }
      {
        name: 'snet-postgres'
        properties: {
          addressPrefix: '10.40.4.0/24'
          delegations: [{ name: 'pg', properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' } }]
        }
      }
      {
        name: 'snet-pe'
        properties: {
          addressPrefix: '10.40.5.0/24'
          networkSecurityGroup: { id: nsgPe.id }
          privateEndpointNetworkPolicies: 'Enabled'
        }
      }
    ]
  }
}

resource dnsZones 'Microsoft.Network/privateDnsZones@2020-06-01' = [for z in zones: {
  name: z
  location: 'global'
  tags: tags
}]

resource dnsLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = [for (z, i) in zones: {
  parent: dnsZones[i]
  name: '${prefix}-link'
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: vnet.id } }
}]

output vnetId string = vnet.id
output appGwSubnetId string = '${vnet.id}/subnets/snet-appgw'
output appsSubnetId string = '${vnet.id}/subnets/snet-apps'
output postgresSubnetId string = '${vnet.id}/subnets/snet-postgres'
output peSubnetId string = '${vnet.id}/subnets/snet-pe'
output dnsZoneIds object = {
  blob: dnsZones[0].id
  vault: dnsZones[1].id
  openai: dnsZones[2].id
  cognitive: dnsZones[3].id
  servicebus: dnsZones[4].id
  postgres: dnsZones[5].id
}
