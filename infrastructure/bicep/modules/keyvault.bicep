// Key Vault com autorização RBAC (sem access policies). As fontes do BCB e da CVM são públicas,
// por isso não há segredos de origem; o cofre guarda configurações sensíveis futuras e é referenciado pelo ADF.
param name string
param location string
param tags object
param logAnalyticsId string

@description('Dias de retenção após exclusão (mínimo 7).')
param softDeleteDays int = 7

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: softDeleteDays
    // Purge protection é irreversível; fica desligada em dev para permitir recriar o ambiente.
    enablePurgeProtection: null
    publicNetworkAccess: 'Enabled'
  }
}

resource diag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: kv
  name: 'to-log-analytics'
  properties: {
    workspaceId: logAnalyticsId
    logs: [ { category: 'AuditEvent', enabled: true } ]
  }
}

output id string = kv.id
output name string = kv.name
output uri string = kv.properties.vaultUri
