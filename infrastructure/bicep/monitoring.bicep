// Alertas da plataforma (Fase 5). Deploy separado da fundação:
//   az deployment group create -g rg-findata-<env> -n monitorizacao-<env> -f infrastructure/bicep/monitoring.bicep \
//      -p env=<env> alertEmail=<email>
// Custo: regras de alerta de métricas cobram cêntimos por mês; não há regras de log (pesquisa agendada).
targetScope = 'resourceGroup'

@allowed([ 'dev', 'test', 'prod' ])
param env string
param project string = 'findata'
@description('Endereço que recebe os alertas (o e-mail do responsável pelo ambiente).')
param alertEmail string
@description('Nome do Data Factory do ambiente (saída dataFactoryName do deployment da fundação).')
param dataFactoryName string

var tags = {
  projeto: 'financial-data-platform'
  ambiente: env
  gerido_por: 'bicep'
}

resource adf 'Microsoft.DataFactory/factories@2018-06-01' existing = {
  name: dataFactoryName
}

resource ag 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'ag-${project}-${env}'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: '${project}${env}'
    enabled: true
    emailReceivers: [
      { name: 'responsavel', emailAddress: alertEmail, useCommonAlertSchema: true }
    ]
  }
}

// Qualquer pipeline do ADF que falhe (inclui falhas dos jobs Databricks, da qualidade e da frescura).
resource adfFalhou 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alr-${project}-${env}-adf-pipeline-falhou'
  location: 'global'
  tags: tags
  properties: {
    description: 'Um pipeline do Data Factory terminou em falha. Ver ADF Monitor e control.pipeline_execution.'
    severity: 1
    enabled: true
    scopes: [ adf.id ]
    evaluationFrequency: 'PT15M'
    windowSize: 'PT15M'
    autoMitigate: false
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          criterionType: 'StaticThresholdCriterion'
          name: 'falhas'
          metricName: 'PipelineFailedRuns'
          metricNamespace: 'Microsoft.DataFactory/factories'
          operator: 'GreaterThan'
          threshold: 0
          timeAggregation: 'Total'
        }
      ]
    }
    actions: [ { actionGroupId: ag.id } ]
  }
}

// Gatilho que falha ao disparar (ex.: pipeline removido ou parâmetros inválidos).
resource triggerFalhou 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alr-${project}-${env}-adf-trigger-falhou'
  location: 'global'
  tags: tags
  properties: {
    description: 'Um gatilho do Data Factory falhou.'
    severity: 2
    enabled: true
    scopes: [ adf.id ]
    evaluationFrequency: 'PT1H'
    windowSize: 'PT1H'
    autoMitigate: false
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          criterionType: 'StaticThresholdCriterion'
          name: 'falhas'
          metricName: 'TriggerFailedRuns'
          metricNamespace: 'Microsoft.DataFactory/factories'
          operator: 'GreaterThan'
          threshold: 0
          timeAggregation: 'Total'
        }
      ]
    }
    actions: [ { actionGroupId: ag.id } ]
  }
}

output actionGroupId string = ag.id
