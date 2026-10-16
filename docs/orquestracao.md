# Orquestração e alertas (Fase 5)

## Decisão: o ADF é o único agendador
- **Alternativas:** (A) agendamentos dos próprios jobs Databricks; (B) ADF dispara os jobs.
- **Escolha: B.** O ADF agenda, passa parâmetros, encadeia dependências entre fontes, aplica retries e concentra a
  monitorização (ADF Monitor + Log Analytics + alertas Azure Monitor). Os agendamentos dos jobs Databricks ficam
  **em pausa de propósito**, para nada correr duas vezes.
- O ADF chama a atividade `DatabricksJob` através do linked service `ls_databricks_findata` com a identidade gerida
  do ADF (papel `Contributor` no workspace, atribuído por `scripts/deploy_rbac.sh`). Não há tokens nem segredos.

```text
tr_diario_dias_uteis (seg–sex 20:30 BRT)          tr_semanal_domingo (dom 06:00 BRT)
        │                                                   │
pl_findata_diario                                   pl_findata_semanal
  ├─ BCB ─► pl_databricks_job(findata_dev_bcb) ──┐    ├─ Auditoria ─► findata_dev_auditoria
  ├─ CVM ─► pl_databricks_job(findata_dev_cvm) ──┤    │     (testes de integração + reconciliação)
  ├─ B3  ─► pl_databricks_job(findata_dev_b3)  ──┤    └─ B3 proventos ─► findata_dev_b3_proventos
  └─ Frescura (só se as três tiverem sucesso) ◄──┘           └─ Modelo ─► findata_dev_ml
       └─ pl_databricks_job(findata_dev_frescura)                (features, walk-forward, ranking)
```

Dentro de cada job Databricks: `bronze → silver → gold (→ reapresentações)`:
- CVM: inclui também o FCA, a DFP/ITR e a tarefa `gold_fundamentos`;
- B3: COTAHIST, com Auto Loader na bronze e Change Data Feed na gold ([streaming.md](streaming.md));
- B3 proventos: dividendos, JCP, eventos oficiais e número de ações ([fundamentos.md](fundamentos.md));
- ML: `ml_features → ml_treino`, com MLflow e registo no Unity Catalog ([modelo_preditivo.md](modelo_preditivo.md)).

Os IDs dos jobs vêm de `deploy_adf.py` (`job_id_bcb`, `job_id_cvm`, `job_id_b3`, `job_id_b3_proventos`,
`job_id_ml`, `job_id_frescura`, `job_id_auditoria`).

## Parâmetros e rastreabilidade
`pl_databricks_job` recebe `job_id`, `run_mode`, `data_inicio`, `data_fim`, `entidades` e envia ao job
`pipeline_run_id = adf-<job_id>-<RunId do ADF>`. Esse valor aparece em todas as tabelas `control.*`, por isso uma
execução do ADF liga-se diretamente às linhas de execução, qualidade, ficheiros e reapresentações:

```sql
SELECT * FROM findata_dev.control.pipeline_execution WHERE pipeline_run_id LIKE 'adf-%<RunId>';
```

Reprocessar um intervalo pelo ADF: *Trigger now* em `pl_databricks_job` com `run_mode = reprocess`, `data_inicio`,
`data_fim` e, se preciso, `entidades`.

## Retries e tempos
| Nível | Política |
|---|---|
| ADF `DatabricksJob` | timeout 2 h, 1 retry após 10 min |
| Tarefas bronze (Databricks) | 2 retries, intervalo 5 min (falhas de rede ou da fonte) |
| Silver/gold | sem retry: falhas de dados não se resolvem a repetir; o pipeline seguinte reapanha a bronze pendente |
| Cliente HTTP | 5 tentativas com backoff exponencial em 429/5xx, 1 pedido/s (WAF do BCB) |
| Jobs Databricks | `max_concurrent_runs = 1` (o ADF não sobrepõe execuções do mesmo job) |

## Frescura (`notebooks/audit/frescura.py`, `config/sla.yaml`)
Falha o pipeline diário quando um watermark passa do prazo (padrão: SGS/PTAX 5 dias, CVM 7; IBC-Br 130, Selic do mês
45), quando um pipeline bronze não tem sucesso há mais de 96 h, ou quando há execuções presas em `RUNNING` há mais de
6 h. Resultado em `control.data_quality_results`.

## Alertas (`infrastructure/bicep/monitoring.bicep`, deploy `monitorizacao-dev`)
| Alerta | Sinal | Severidade |
|---|---|---|
| `alr-findata-dev-adf-pipeline-falhou` | métrica `PipelineFailedRuns` > 0 em 15 min | 1 |
| `alr-findata-dev-adf-trigger-falhou` | métrica `TriggerFailedRuns` > 0 em 1 h | 2 |

Ambos enviam e-mail pelo grupo de ação `ag-findata-dev`. Os jobs Databricks também enviam e-mail em falha.
O orçamento `limite-credito-175` (subscrição) alerta a 25/50/75/90 % e previsão > 100 %.

## Operação
```bash
python scripts/deploy_workspace.py --env dev     # jobs Databricks (mantém o estado dos agendamentos)
python scripts/deploy_adf.py --env dev           # linked service, pipelines e gatilhos (gatilhos novos ficam parados)
python scripts/deploy_adf.py --env dev --run pl_findata_diario   # execução única
```
Ativar o agendamento: ADF Studio → **Gerir → Gatilhos** → `tr_diario_dias_uteis` e `tr_semanal_domingo` → **Iniciar**
(ou `az rest --method post --url https://management.azure.com/<fábrica>/triggers/<nome>/start?api-version=2018-06-01`).
O `deploy_adf.py` não altera gatilhos iniciados (para não desligar o agendamento em silêncio).

## Custo
Cada execução diária usa serverless só enquanto corre (BCB ~10 min, CVM incremental ~5 min, B3 incremental ~5 min, frescura ~1 min). Semanal: proventos ~10 min (725 pedidos à B3), modelo ~10 min, auditoria ~10 min.
ADF: 3–4 execuções de atividade por dia mais o tempo de espera das atividades externas (cêntimos por mês).
As duas regras de alerta de métricas custam cêntimos por mês.
