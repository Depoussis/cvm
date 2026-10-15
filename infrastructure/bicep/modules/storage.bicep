// ADLS Gen2 do lakehouse. Um contêiner por finalidade para separar ficheiros originais, camadas Delta,
// checkpoints, quarentena e auditoria (requisito do projeto) e permitir permissões diferentes por contêiner.
@description('Nome da conta de armazenamento (3-24 caracteres minúsculos).')
param name string
param location string
param tags object

@description('Contêineres criados na conta.')
param containers array = [
  'raw'         // ficheiros e payloads originais, imutáveis (nunca sobrescritos)
  'bronze'      // tabelas Delta bronze (managed location do schema bronze no Unity Catalog)
  'silver'
  'gold'
  'control'     // tabelas de controlo e auditoria
  'checkpoints' // checkpoints de streaming/Auto Loader
  'quarantine'  // payloads inválidos e ficheiros corrompidos
]

@description('Dias de retenção de blobs e contêineres apagados (soft delete).')
param softDeleteDays int = 7

resource conta 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' } // dev/teste: LRS é o mais barato; produção deve usar ZRS/GRS
  kind: 'StorageV2'
  properties: {
    isHnsEnabled: true // ADLS Gen2
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false // acesso só por Entra ID / Managed Identity, sem chaves de conta
    defaultToOAuthAuthentication: true
    publicNetworkAccess: 'Enabled' // dev: rede pública com autenticação Entra; produção: private endpoints
    encryption: {
      keySource: 'Microsoft.Storage' // encriptação em repouso com chaves geridas pela Microsoft
      services: {
        blob: { enabled: true }
        file: { enabled: true }
      }
    }
  }
}

resource blob 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: conta
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: softDeleteDays }
    containerDeleteRetentionPolicy: { enabled: true, days: softDeleteDays }
  }
}

resource cont 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for c in containers: {
  parent: blob
  name: c
  properties: { publicAccess: 'None' }
}]

output id string = conta.id
output name string = conta.name
output dfsEndpoint string = conta.properties.primaryEndpoints.dfs
