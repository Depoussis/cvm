# Pipelines do Banco Central (Fase 2)

Job Databricks **`findata_dev_bcb`** (serverless), criado por `scripts/deploy_workspace.py`.
Código publicado em `/Workspace/Shared/findata_dev/`.

```text
bronze_sgs  ──► silver_sgs  ──┐
                              ├──► gold_bcb
bronze_ptax ──► silver_ptax ──┘
```

## Fontes (verificadas com pedidos reais em 16/10/2026)

| Fonte | Endpoint | Notas |
|---|---|---|
| SGS | `https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json&dataInicial=dd/MM/aaaa&dataFinal=dd/MM/aaaa` | 404 "Value(s) not found" = janela sem dados; 406 se a janela de uma série diária passar de 10 anos (usamos 5) |
| PTAX moedas | `https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/Moedas` | 10 moedas: AUD, CAD, CHF, DKK, EUR, GBP, JPY, NOK, SEK, USD |
| PTAX cotações | `.../odata/CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)` | datas `'MM-dd-aaaa'`; boletins Abertura, Intermediário e Fechamento |

O portal de dados abertos do BCB e as APIs têm um firewall que devolve **403** a rajadas de pedidos. O cliente
HTTP faz 1 pedido por segundo, com retries e backoff exponencial em 429/5xx.

### Séries SGS carregadas
Só códigos confirmados no portal dadosabertos.bcb.gov.br (ver `config/series/bcb_sgs.yaml`):

| Código | Série | Periodicidade |
|---|---|---|
| 432 | Meta Selic definida pelo Copom | diária (publica datas futuras até à próxima reunião) |
| 11 | Selic | diária |
| 1178 | Selic anualizada base 252 | diária |
| 4390 | Selic acumulada no mês | mensal |
| 1 | Dólar americano (venda), câmbio livre | diária |
| 10813 | Dólar americano (compra), câmbio livre | diária |
| 24363 | IBC-Br | mensal |

O IPCA e o CDI não entraram: os códigos habituais não aparecem no portal de dados abertos com esse número, e o
projeto não usa códigos sem confirmação oficial. Para os acrescentar, confirmar o código e juntar ao YAML.

## Tabelas

| Camada | Tabela | Chave | Escrita |
|---|---|---|---|
| raw | volume `ops.raw/<fonte>/<entidade>/ingestion_date=…/<run>/` | — | payload original, nunca sobrescrito |
| bronze | `bronze.bcb_sgs_valores`, `bronze.bcb_ptax_cotacoes`, `bronze.bcb_ptax_moedas` | — | append, texto original + auditoria |
| silver | `silver.bcb_sgs_valores` | (serie_codigo, data_referencia) | SCD1 por `record_hash` |
| silver | `silver.bcb_ptax_cotacoes` | (moeda, data_hora_cotacao, tipo_boletim) | SCD1 |
| silver | `silver.bcb_sgs_series`, `silver.bcb_ptax_moedas` | serie_codigo / simbolo | SCD2 (`valid_from`, `valid_to`, `is_current`) |
| gold | `dim_data`, `dim_serie`, `dim_moeda`, `fct_serie_valor`, `fct_ptax_diario` | ver DDL | `INSERT OVERWRITE` |
| gold | `vw_juros_cambio_diario`, `vw_serie_ultimo_valor` | — | vistas |

## Modos de execução (parâmetro `run_mode` do job)

| Modo | Intervalo pedido à fonte | Silver lê da bronze |
|---|---|---|
| `incremental` (agendado) | watermark − `revisao_dias` até hoje | linhas de execuções ainda não consolidadas |
| `backfill` | `inicio_backfill` até hoje | idem |
| `reprocess` | `data_inicio`..`data_fim` | toda a bronze da entidade |

- **Idempotência:** um payload com o mesmo sha256 de outro já processado fica `DUPLICATE` no registo de ficheiros e
  não volta à bronze. Na silver, o MERGE só atualiza quando o `record_hash` muda.
- **Watermark** (`control.ingestion_watermark`): última data de referência na silver; só avança se as regras
  CRITICAL passarem, e nunca recua.
- **Falhas:** cada entidade regista `RUNNING` → `SUCCEEDED`/`FAILED` em `control.pipeline_execution`. Uma falha numa
  série não impede as outras; a tarefa falha no fim. Dados de uma silver falhada são reapanhados na execução seguinte.
- **Filtrar entidades:** parâmetro `entidades`, ex.: `serie_432,cotacao_USD`.

## Qualidade (`control.data_quality_results`)

| Regra | Tabela | Severidade |
|---|---|---|
| chave única | silver SGS e PTAX | CRITICAL |
| cotações e paridades > 0 | silver PTAX | CRITICAL |
| formato da API convertível sem perda (inválidos vão para `ops.quarantine`) | bronze | HIGH |
| sem datas futuras (exceto meta Selic) | silver SGS | HIGH |
| venda ≥ compra; boletim conhecido; um único valor de fechamento por dia | silver PTAX | HIGH |
| fechamento repetido com os mesmos valores (o BCB publicou 2× em 23/04/2025) | silver PTAX | INFO |
| uma linha por (moeda, dia) | gold | CRITICAL |
| datas da gold existem em `dim_data` | gold | HIGH |
| SGS 1 (dólar venda) = PTAX USD fechamento venda | gold | INFO |

CRITICAL e HIGH bloqueiam a publicação gold da execução (`gold_bcb` falha sem escrever).

## Operação

```bash
python scripts/apply_sql.py --env dev --dir sql/schemas --dir sql/dimensions --dir sql/facts --dir sql/views
python scripts/deploy_workspace.py --env dev                 # publica código e atualiza o job
python scripts/deploy_workspace.py --env dev --run backfill  # e corre o histórico
```

O agendamento (dias úteis às 20:00 de Brasília) é criado em **pausa**. Para ativar: Databricks → Jobs →
`findata_dev_bcb` → Schedule → *Unpause*.

Consultas úteis:
```sql
SELECT * FROM findata_dev.control.pipeline_execution ORDER BY start_timestamp DESC LIMIT 50;
SELECT * FROM findata_dev.control.data_quality_results WHERE result = 'FAILED';
SELECT * FROM findata_dev.gold.vw_juros_cambio_diario ORDER BY data DESC;
```
