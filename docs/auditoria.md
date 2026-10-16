# Histórico e auditoria (Fase 4)

## O que guarda o histórico

| Mecanismo | Onde | Para quê |
|---|---|---|
| Originais imutáveis | volume `ops.raw` | refazer qualquer carga a partir do que a fonte entregou |
| Bronze append-only | `bronze.*` | todas as versões recebidas, com hash do ficheiro e do registo |
| Registo de ficheiros | `control.source_file_registry` | URL, ETag, Last-Modified, sha256, versão e estado de cada ficheiro |
| SCD1 + Change Data Feed | `silver.bcb_sgs_valores`, `silver.bcb_ptax_cotacoes`, `silver.cvm_fi_informe_diario` | valor atual; as alterações ficam no CDF |
| Reapresentações | `control.reapresentacoes` | cada valor revisto: antes → depois, colunas alteradas, versão Delta, execução |
| SCD2 | `silver.bcb_sgs_series`, `silver.bcb_ptax_moedas`, `silver.cvm_fundo*`, `silver.cvm_companhia` | todas as versões dos cadastros (`valid_from`, `valid_to`, `is_current`) |
| Watermarks | `control.ingestion_watermark` | último ponto confirmado (nunca recua) e última reconciliação completa |
| Reconciliação | `control.reconciliation_results` | comparação periódica com a fonte |

## Reapresentações
`notebooks/audit/reapresentacoes.py` corre no fim dos jobs BCB e CVM. Lê `table_changes()` desde a última versão
processada (watermark `delta_version` por tabela, em `ingestion_watermark` com `source_system = 'auditoria'`) e
emparelha `update_preimage`/`update_postimage` da mesma versão. Como o MERGE SCD1 só atualiza quando o
`record_hash` muda, cada par é uma alteração real.

```sql
SELECT * FROM findata_dev.gold.vw_reapresentacoes_resumo ORDER BY dia DESC;
SELECT chave, valores_anteriores, valores_novos, colunas_alteradas
FROM findata_dev.control.reapresentacoes WHERE table_name LIKE '%bcb_sgs_valores';
```

Primeira deteção (16/10/2026): 19 976 linhas do informe diário mudaram quando a regra de desempate entre `FI` e
`CLASSES - FIF` passou a preferir o regime novo (ver `docs/pipelines_cvm.md`). É uma correção da plataforma, não da
fonte; identifica-se pelo `pipeline_run_id` (`job-814569625103644`).

## Reconciliação com a fonte
`notebooks/audit/reconciliacao.py`, job semanal `findata_dev_auditoria` (domingo 06:00):

| Fonte | Como compara |
|---|---|
| SGS | pede o histórico completo de cada série à API e compara chave a chave com a silver |
| PTAX | idem por moeda, desde `inicio_backfill` |
| CVM informe diário | por mês: `HEAD` confirma que o ficheiro na fonte é o último carregado (senão `FONTE_ATUALIZADA`); depois compara esse ficheiro com a silver |

Resultados: `OK`, `DIVERGENTE` (com amostra em `detalhe`), `FONTE_ATUALIZADA` ou `ERRO`. Entidades `OK` atualizam
`last_full_reconciliation` no watermark.

Limitação conhecida: o SCD1 não apaga. Se a fonte retirar um registo numa republicação, ele aparece na
reconciliação como `so_na_plataforma`; a decisão de apagar fica para revisão manual.

## Consultas no tempo (SCD2)
```sql
SELECT * FROM findata_dev.gold.fn_fundo_classe_em(TIMESTAMP'2026-10-16 12:00:00');
SELECT * FROM findata_dev.gold.fn_companhia_em(current_timestamp()) WHERE uf = 'SP';
SELECT * FROM findata_dev.gold.vw_companhia_historico WHERE cnpj_cia = '33000167000101' ORDER BY valid_from;
```
`valid_from`/`valid_to` são tempo de processamento (quando a plataforma soube da mudança). As datas de vigência
declaradas pela fonte estão nas próprias colunas (`data_inicio_situacao`, `dt_ini_sit`, …).

Para a silver SCD1 há também o time travel do Delta (`SELECT … VERSION AS OF n`), limitado pela retenção (7 dias
por omissão para ficheiros removidos).

## Testes de integração
`notebooks/tests/integracao.py` (primeira tarefa do job de auditoria) cria tabelas temporárias em `ops` e verifica
com Spark/Delta reais: contagens do SCD1, deteção de reapresentação pelo CDF, SCD2 (alteração, chave ausente,
reaparecimento, uma versão atual por chave), watermark que não recua e registo de execuções. Limpa tudo no fim.
