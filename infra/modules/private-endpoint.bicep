// Reusable private endpoint + DNS registration for one PaaS sub-resource.
param location string
param name string
param subnetId string
param targetId string
param groupId string
param dnsZoneId string
param tags object

resource pe 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    subnet: { id: subnetId }
    privateLinkServiceConnections: [
      { name: name, properties: { privateLinkServiceId: targetId, groupIds: [groupId] } }
    ]
  }
}

resource dns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: pe
  name: 'default'
  properties: { privateDnsZoneConfigs: [{ name: 'zone', properties: { privateDnsZoneId: dnsZoneId } }] }
}
