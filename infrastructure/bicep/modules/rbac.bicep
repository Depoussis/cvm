// Atribuições de funções (mínimo necessário). Separado do resto porque exige Owner ou User Access Administrator.
param storageName string
param keyVaultName string
param databricksWorkspaceName string
param accessConnectorPrincipalId string
param dataFactoryPrincipalId string

@description('Object ID do utilizador/grupo de engenharia que administra o ambiente (vazio = não atribui).')
param adminPrincipalId string = ''
@allowed([ 'User', 'Group' ])
param adminPrincipalType string = 'User'

var roles = {
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  keyVaultSecretsOfficer: 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
  contributor: 'b24988ac-6180-42a0-ab88-20f7382dd24c'
}

resource st 'Microsoft.Storage/storageAccounts@2023-05-01' existing = { name: storageName }
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' existing = { name: keyVaultName }
resource ws 'Microsoft.Databricks/workspaces@2024-05-01' existing = { name: databricksWorkspaceName }

// Unity Catalog lê e escreve as tabelas Delta através do Access Connector.
resource ucStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: st
  name: guid(st.id, accessConnectorPrincipalId, roles.storageBlobDataContributor)
  properties: {
    principalId: accessConnectorPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
  }
}

// ADF grava os ficheiros originais no contêiner raw (download HTTP/REST).
resource adfStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: st
  name: guid(st.id, dataFactoryPrincipalId, roles.storageBlobDataContributor)
  properties: {
    principalId: dataFactoryPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
  }
}

resource adfKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, dataFactoryPrincipalId, roles.keyVaultSecretsUser)
  properties: {
    principalId: dataFactoryPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
  }
}

// O linked service Databricks do ADF com Managed Identity exige Contributor no workspace.
resource adfDbw 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: ws
  name: guid(ws.id, dataFactoryPrincipalId, roles.contributor)
  properties: {
    principalId: dataFactoryPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.contributor)
  }
}

resource adminStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(adminPrincipalId)) {
  scope: st
  name: guid(st.id, adminPrincipalId, roles.storageBlobDataContributor)
  properties: {
    principalId: adminPrincipalId
    principalType: adminPrincipalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
  }
}

resource adminKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(adminPrincipalId)) {
  scope: kv
  name: guid(kv.id, adminPrincipalId, roles.keyVaultSecretsOfficer)
  properties: {
    principalId: adminPrincipalId
    principalType: adminPrincipalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsOfficer)
  }
}
