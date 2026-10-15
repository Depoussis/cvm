// Azure Data Factory (orquestração). Identidade gerida do sistema para aceder ao ADLS, Key Vault e Databricks.
param name string
param location string
param tags object
param logAnalyticsId string

resource adf 'Microsoft.DataFactory/factories@2018-06-01' = {
  name: name
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    publicNetworkAccess: 'Enabled'
  }
}

resource diag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: adf
  name: 'to-log-analytics'
  properties: {
    workspaceId: logAnalyticsId
    logAnalyticsDestinationType: 'Dedicated' // tabelas ADFPipelineRun/ADFActivityRun em vez de AzureDiagnostics
    logs: [
      { category: 'PipelineRuns', enabled: true }
      { category: 'ActivityRuns', enabled: true }
      { category: 'TriggerRuns', enabled: true }
    ]
  }
}

output id string = adf.id
output name string = adf.name
output principalId string = adf.identity.principalId
