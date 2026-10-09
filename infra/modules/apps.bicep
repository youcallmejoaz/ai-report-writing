// Internal-only Container Apps environment hosting the API and pipeline workers.
param location string
param prefix string
param tags object
param subnetId string
param workspaceId string
param appIdentityId string
param appIdentityClientId string
param registryServer string
param apiImage string
param workerImage string
param env array

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: last(split(workspaceId, '/'))
}

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-cae'
  location: location
  tags: tags
  properties: {
    vnetConfiguration: { infrastructureSubnetId: subnetId, internal: true }
    zoneRedundant: true
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: { customerId: law.properties.customerId, sharedKey: law.listKeys().primarySharedKey }
    }
  }
}

var commonEnv = concat(env, [{ name: 'AZURE_CLIENT_ID', value: appIdentityClientId }, { name: 'APP_ENV', value: 'production' }])

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-api'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${appIdentityId}': {} } }
  properties: {
    environmentId: cae.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: { external: false, targetPort: 8000, transport: 'http', allowInsecure: false }
      registries: [{ server: registryServer, identity: appIdentityId }]
    }
    template: {
      containers: [{
        name: 'api'
        image: apiImage
        resources: { cpu: json('1.0'), memory: '2Gi' }
        env: commonEnv
        probes: [{ type: 'Liveness', httpGet: { path: '/health', port: 8000 } }]
      }]
      scale: { minReplicas: 2, maxReplicas: 6 }
    }
  }
}

resource worker 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-worker'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${appIdentityId}': {} } }
  properties: {
    environmentId: cae.id
    workloadProfileName: 'Consumption'
    configuration: { registries: [{ server: registryServer, identity: appIdentityId }] }
    template: {
      containers: [{
        name: 'worker'
        image: workerImage
        resources: { cpu: json('2.0'), memory: '4Gi' }
        env: commonEnv
      }]
      // Build phase: KEDA azure-servicebus scale rule on queue depth using the managed identity.
      scale: { minReplicas: 1, maxReplicas: 10 }
    }
  }
}

output environmentStaticIp string = cae.properties.staticIp
output apiFqdn string = api.properties.configuration.ingress.fqdn
