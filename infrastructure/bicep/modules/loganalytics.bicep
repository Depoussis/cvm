// Log Analytics para logs do ADF, Databricks e Key Vault. A quota diária limita o custo de ingestão.
param name string
param location string
param tags object

@description('Limite diário de ingestão em GB (-1 = sem limite). Ao atingir, a ingestão para até ao dia seguinte.')
param dailyQuotaGb int = 1
param retentionDays int = 30

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: retentionDays
    workspaceCapping: { dailyQuotaGb: dailyQuotaGb }
  }
}

output id string = law.id
output name string = law.name
