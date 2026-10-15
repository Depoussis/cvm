// Fundação da plataforma (Fase 1): ADLS Gen2, Key Vault, Log Analytics, Databricks + Access Connector e Data Factory.
// Implementado num resource group por ambiente. As atribuições de funções estão em rbac.bicep (deploy separado).
targetScope = 'resourceGroup'

@allowed([ 'dev', 'test', 'prod' ])
param env string
param location string = resourceGroup().location
@description('Prefixo curto do projeto, usado nos nomes dos recursos.')
param project string = 'findata'
@description('Sufixo para nomes globalmente únicos (storage, key vault).')
param suffix string = substring(uniqueString(subscription().id, resourceGroup().id), 0, 6)

@allowed([ 'trial', 'premium' ])
param databricksSku string = 'premium'
param databricksNoPublicIp bool = false
param logDailyQuotaGb int = 1

var tags = {
  projeto: 'financial-data-platform'
  ambiente: env
  gerido_por: 'bicep'
}

module law 'modules/loganalytics.bicep' = {
  name: 'law'
  params: {
    name: 'log-${project}-${env}'
    location: location
    tags: tags
    dailyQuotaGb: logDailyQuotaGb
  }
}

module st 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    name: 'st${project}${env}${suffix}'
    location: location
    tags: tags
  }
}

module kv 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    name: 'kv-${project}-${env}-${suffix}'
    location: location
    tags: tags
    logAnalyticsId: law.outputs.id
  }
}

module dbw 'modules/databricks.bicep' = {
  name: 'databricks'
  params: {
    workspaceName: 'dbw-${project}-${env}'
    accessConnectorName: 'ac-${project}-${env}'
    location: location
    tags: tags
    logAnalyticsId: law.outputs.id
    sku: databricksSku
    enableNoPublicIp: databricksNoPublicIp
  }
}

module adf 'modules/datafactory.bicep' = {
  name: 'datafactory'
  params: {
    name: 'adf-${project}-${env}-${suffix}'
    location: location
    tags: tags
    logAnalyticsId: law.outputs.id
  }
}

output storageAccountName string = st.outputs.name
output storageDfsEndpoint string = st.outputs.dfsEndpoint
output keyVaultName string = kv.outputs.name
output keyVaultUri string = kv.outputs.uri
output logAnalyticsId string = law.outputs.id
output databricksWorkspaceName string = 'dbw-${project}-${env}'
output databricksWorkspaceUrl string = dbw.outputs.workspaceUrl
output accessConnectorId string = dbw.outputs.accessConnectorId
output accessConnectorPrincipalId string = dbw.outputs.accessConnectorPrincipalId
output dataFactoryName string = adf.outputs.name
output dataFactoryPrincipalId string = adf.outputs.principalId
