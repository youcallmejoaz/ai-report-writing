// Subscription guardrails: UK regions only; Azure OpenAI deployments must be Standard (regional) or
// regional provisioned, never Global or DataZone, which can process data outside the UK.
targetScope = 'subscription'

param allowedLocations array = ['uksouth', 'ukwest', 'global']

resource denyNonRegionalAoai 'Microsoft.Authorization/policyDefinitions@2023-04-01' = {
  name: 'deny-non-regional-openai-deployments'
  properties: {
    displayName: 'Azure OpenAI deployments must use regional SKUs (UK data residency)'
    policyType: 'Custom'
    mode: 'All'
    policyRule: {
      if: {
        allOf: [
          { field: 'type', equals: 'Microsoft.CognitiveServices/accounts/deployments' }
          { field: 'Microsoft.CognitiveServices/accounts/deployments/sku.name', notIn: ['Standard', 'ProvisionedManaged'] }
        ]
      }
      then: { effect: 'deny' }
    }
  }
}

resource assignAoai 'Microsoft.Authorization/policyAssignments@2024-04-01' = {
  name: 'aoai-regional-only'
  properties: { policyDefinitionId: denyNonRegionalAoai.id, enforcementMode: 'Default' }
}

resource assignLocations 'Microsoft.Authorization/policyAssignments@2024-04-01' = {
  name: 'uk-locations-only'
  properties: {
    displayName: 'Allowed locations: UK only'
    policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', 'e56962a6-4747-49cd-b67b-bf8b01975c4c')
    parameters: { listOfAllowedLocations: { value: allowedLocations } }
    enforcementMode: 'Default'
  }
}
