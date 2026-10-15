// Workspace Azure Databricks + Access Connector (identidade gerida usada pelo Unity Catalog para aceder ao ADLS).
param workspaceName string
param accessConnectorName string
param location string
param tags object
param logAnalyticsId string

@allowed([ 'trial', 'premium' ])
@description('Unity Catalog exige Premium. O tier trial (DBUs grátis por 14 dias) não é permitido em subscrições Azure Free Trial.')
param sku string = 'premium'

@description('true = Secure Cluster Connectivity (sem IP público). Com a VNet gerida por omissão, isso cria um NAT Gateway, que cobra mesmo com o workspace ocioso.')
param enableNoPublicIp bool = false

var managedRgName = 'rg-${workspaceName}-managed'

resource ws 'Microsoft.Databricks/workspaces@2024-05-01' = {
  name: workspaceName
  location: location
  tags: tags
  sku: { name: sku }
  properties: {
    managedResourceGroupId: subscriptionResourceId('Microsoft.Resources/resourceGroups', managedRgName)
    parameters: {
      enableNoPublicIp: { value: enableNoPublicIp }
    }
  }
}

resource connector 'Microsoft.Databricks/accessConnectors@2024-05-01' = {
  name: accessConnectorName
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {}
}

resource diag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: ws
  name: 'to-log-analytics'
  properties: {
    workspaceId: logAnalyticsId
    logs: [
      { category: 'jobs', enabled: true }
      { category: 'clusters', enabled: true }
      { category: 'unityCatalog', enabled: true }
      { category: 'accounts', enabled: true }
    ]
  }
}

output workspaceId string = ws.id
output workspaceUrl string = ws.properties.workspaceUrl
output accessConnectorId string = connector.id
output accessConnectorPrincipalId string = connector.identity.principalId
