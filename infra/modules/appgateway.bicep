// Application Gateway WAF v2 (OWASP 3.2, Prevention mode) in front of the internal Container Apps API.
param location string
param prefix string
param tags object
param subnetId string
param backendFqdn string
@description('Key Vault secret URI of the TLS certificate for the public hostname (not the secret itself).')
#disable-next-line secure-secrets-in-params
param tlsCertSecretId string
param gatewayIdentityId string

resource pip 'Microsoft.Network/publicIPAddresses@2023-11-01' = {
  name: '${prefix}-agw-pip'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  zones: ['1', '2', '3']
  properties: { publicIPAllocationMethod: 'Static' }
}

resource waf 'Microsoft.Network/ApplicationGatewayWebApplicationFirewallPolicies@2023-11-01' = {
  name: '${prefix}-waf'
  location: location
  tags: tags
  properties: {
    policySettings: { state: 'Enabled', mode: 'Prevention', requestBodyCheck: true, maxRequestBodySizeInKb: 128, fileUploadLimitInMb: 50 }
    managedRules: { managedRuleSets: [{ ruleSetType: 'OWASP', ruleSetVersion: '3.2' }] }
  }
}

var gwName = '${prefix}-agw'

resource agw 'Microsoft.Network/applicationGateways@2023-11-01' = {
  name: gwName
  location: location
  tags: tags
  zones: ['1', '2', '3']
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${gatewayIdentityId}': {} } }
  properties: {
    sku: { name: 'WAF_v2', tier: 'WAF_v2' }
    autoscaleConfiguration: { minCapacity: 1, maxCapacity: 4 }
    firewallPolicy: { id: waf.id }
    sslPolicy: { policyType: 'Predefined', policyName: 'AppGwSslPolicy20220101S' }
    gatewayIPConfigurations: [{ name: 'gwip', properties: { subnet: { id: subnetId } } }]
    frontendIPConfigurations: [{ name: 'public', properties: { publicIPAddress: { id: pip.id } } }]
    frontendPorts: [{ name: 'https', properties: { port: 443 } }]
    sslCertificates: [{ name: 'site', properties: { keyVaultSecretId: tlsCertSecretId } }]
    backendAddressPools: [{ name: 'api', properties: { backendAddresses: [{ fqdn: backendFqdn }] } }]
    probes: [{
      name: 'health'
      properties: { protocol: 'Https', path: '/health', interval: 30, timeout: 30, unhealthyThreshold: 3, pickHostNameFromBackendHttpSettings: true }
    }]
    backendHttpSettingsCollection: [{
      name: 'api-https'
      properties: {
        port: 443
        protocol: 'Https'
        pickHostNameFromBackendAddress: true
        requestTimeout: 120
        probe: { id: resourceId('Microsoft.Network/applicationGateways/probes', gwName, 'health') }
      }
    }]
    httpListeners: [{
      name: 'https'
      properties: {
        frontendIPConfiguration: { id: resourceId('Microsoft.Network/applicationGateways/frontendIPConfigurations', gwName, 'public') }
        frontendPort: { id: resourceId('Microsoft.Network/applicationGateways/frontendPorts', gwName, 'https') }
        protocol: 'Https'
        sslCertificate: { id: resourceId('Microsoft.Network/applicationGateways/sslCertificates', gwName, 'site') }
      }
    }]
    requestRoutingRules: [{
      name: 'api'
      properties: {
        ruleType: 'Basic'
        priority: 100
        httpListener: { id: resourceId('Microsoft.Network/applicationGateways/httpListeners', gwName, 'https') }
        backendAddressPool: { id: resourceId('Microsoft.Network/applicationGateways/backendAddressPools', gwName, 'api') }
        backendHttpSettings: { id: resourceId('Microsoft.Network/applicationGateways/backendHttpSettingsCollection', gwName, 'api-https') }
      }
    }]
  }
}
