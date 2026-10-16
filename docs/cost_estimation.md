# Estimativa de custos (dev)

Preços de tabela da Azure Retail Prices API, em EUR, região North Europe, consultados em 15/10/2026.
A subscrição é **Azure Free Trial** com limite de gastos: ao esgotar o crédito, os recursos são desativados
em vez de cobrados. Há um orçamento `limite-credito-175` com alertas em 25/50/75/90 % e 100 % previsto.

## Preços unitários

| Serviço | Medidor | Preço |
|---|---|---|
| VM `Standard_DS3_v2` (4 vCPU, 14 GB) | por hora | 0,2314 € |
| Databricks Premium Jobs Compute | por DBU-hora (DS3_v2 = 0,75 DBU/h) | 0,264 € |
| Databricks Premium All-purpose Compute | por DBU-hora | 0,484 € |
| Databricks Premium Serverless SQL | por DBU-hora (2X-Small = 4 DBU/h) | 0,8008 € |
| Databricks Premium Automated Serverless Compute | por DBU-hora | 0,4136 € |
| Data Factory: execução de atividade (Azure IR) | por 1000 | 0,88 € |
| Data Factory: atividade externa (ex.: Databricks) | por hora | 0,0002 € |
| Log Analytics: ingestão | por GB (5 GB/mês grátis por conta de faturação) | 2,4287 € |
| ADLS Gen2 Hot LRS | por GB/mês | cêntimos |

## Custo por cenário

| Cenário | Cálculo | Custo |
|---|---|---|
| Cluster de jobs single-node DS3_v2 | 0,2314 + 0,75 × 0,264 | **≈ 0,43 €/h** |
| Cluster interativo (all-purpose) DS3_v2 | 0,2314 + 0,75 × 0,484 | **≈ 0,59 €/h** |
| SQL Warehouse serverless 2X-Small | 4 × 0,8008 | **≈ 3,20 €/h** (só enquanto ligado; auto-stop 1 min) |
| Incremental diário (BCB + CVM), ~20 min/dia | 0,43 × 20/60 × 30 | ≈ 4,30 €/mês |
| Backfill histórico CVM (estimativa 3–6 h, uma vez) | 0,43 × 6 | ≈ 2,60 € |
| ADF: ~10 atividades/dia | 300 × 0,00088 + externas | < 0,50 €/mês |
| Log Analytics (quota 1 GB/dia) | máximo 30 GB | ≤ 60 €/mês no pior caso; esperado < 5 GB (grátis) |

**Previsão para dev:** 10–15 €/mês com uso normal, mais o backfill único.

## Jobs serverless (Fase 2)
O job `findata_dev_bcb` corre em **serverless** (Automated Serverless Compute, 0,4136 €/DBU-hora): no Free Trial o
Databricks reporta os tipos de VM clássicos como `NotEnabledOnSubscription`, e o serverless não usa a quota de vCPUs.
Só há custo enquanto o job corre; não existe cluster parado. O consumo real fica em `system.billing.usage`
(quando as system tables estão ativas) e na fatura Azure do workspace.

## Recursos que custam mesmo parados

| Recurso | Custo ocioso | Mitigação |
|---|---|---|
| ADLS Gen2 | armazenamento (GB/mês) | lifecycle para Cool em `raw/` antigo (fase 7) |
| Log Analytics | só ingestão; retenção de 30 dias incluída | quota diária |
| Key Vault | nada sem operações | — |
| Workspace Databricks | nada sem clusters/warehouses ligados | auto-termination dos clusters; auto-stop do warehouse |
| Storage gerido do Databricks (`rg-dbw-findata-dev-managed`) | cêntimos | — |
| NAT Gateway | **não existe** (SCC desligado em dev) | em produção com SCC: ≈ 30 €/mês |

## Riscos de custo
- **SQL Warehouse esquecido ligado:** 3,20 €/h. O auto-stop de 1 min mitiga; o tamanho original (Small, ~9,6 €/h)
  foi reduzido no setup.
- **Cluster interativo sem auto-termination:** usar sempre auto-termination de 15–20 min.
- **Quota de 4 vCPU:** impede escalar acidentalmente, o que também limita o custo.
