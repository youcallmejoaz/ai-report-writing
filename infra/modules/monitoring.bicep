param location string
param prefix string
param tags object
@description('Days to retain operational logs. Logs carry identifiers, never client content.')
param retentionDays int = 90

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-law'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: retentionDays
    publicNetworkAccessForIngestion: 'Enabled' // switch to Azure Monitor Private Link Scope in build phase
    publicNetworkAccessForQuery: 'Disabled'
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: '${prefix}-appi'
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
    DisableLocalAuth: true
  }
}

output workspaceId string = law.id
output appInsightsConnectionString string = appi.properties.ConnectionString
