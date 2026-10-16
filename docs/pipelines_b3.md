# Pipelines da B3 (cotações da bolsa)

Job Databricks **`findata_dev_b3`** (serverless), criado por `scripts/deploy_workspace.py --fonte b3`:
`bronze_b3 → silver_b3 → gold_b3`. Agendamento de segunda a sexta às 21:30 de Brasília, criado em pausa. Quem
agenda é o ADF: a atividade `B3` corre em paralelo com BCB e CVM no `pl_findata_diario`.

A ligação ticker → companhia vem da CVM, pelo **Formulário Cadastral (FCA)**. Corre no job da CVM, entidade
`cia_aberta_fca`, e chega à silver como `cvm_valor_mobiliario`.

## Fonte: séries históricas da B3 (COTAHIST)

Tudo confirmado com pedidos reais em 16/10/2026 (`config/datasets/b3.yaml`):

| Ficheiro | URL | Notas |
|---|---|---|
| Anual | `bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_AAAAA.ZIP` | ~85 MB (~1,1 GB descompactado); o do ano corrente é atualizado a cada pregão |
| Diário | `.../COTAHIST_DDDMMAAAA.ZIP` | ~0,7 MB, ~18,8 mil registos; publicado por volta das 20:50 de Brasília; fins de semana e feriados → 404 |

O formato é um TXT de largura fixa (245 posições, ISO-8859-1). Tem um registo `00` (cabeçalho), um `01` por papel e
mercado, e um `99` (trailer). O layout está em `src/ingestion/b3/cotahist.py` e é testado com uma linha real.

- **Preços** com 2 casas implícitas (`0000000005736` = 57,36), cotados por lote de `FATCOT` unidades. A silver divide
  pelo fator.
- **Trailer:** o layout diz que o total inclui cabeçalho e trailer, mas no diário de 15/10/2026 contava só as
  cotações. As duas leituras são aceites; outro valor indica um ficheiro truncado e vai para a quarentena.
- **Volume:** ~55 % das linhas do ficheiro são opções e termo. A bronze guarda só o mercado à vista (`TPMERC 010`) e
  o ficheiro completo fica no volume raw.
- **Sem índices:** o Ibovespa não vem no COTAHIST, só papéis. O painel usa o **BOVA11**, ETF que o replica.

## Camadas

**Nota sobre o FCA:** a espécie declarada pelas companhias nem sempre está certa. Por exemplo, a MGLU3 aparece como
"Ações Preferenciais" em 2025 e em 2026, e 18 tickers têm duas espécies no mesmo formulário. Por isso a gold tira a
espécie (ON/PN/Unit) da especificação da B3 e usa o FCA só para o CNPJ e o segmento de listagem. Também há tickers
mal preenchidos: a CSN declara "4030", o BTG "000000" e a Klabin só a unit KLBN11. Quando falta o ticker exato, a
gold usa a raiz de 4 letras (KLBN4 → KLBN11), desde que essa raiz aponte para uma única companhia; as restantes ficam
na regra INFO `acao_sem_emissor`.

**IBOV11:** o COTAHIST traz em lote padrão (BDI 02) uma cesta do Ibovespa (`IBO/`, cerca de índice/100) com
negócios esporádicos. Fica na silver e é excluída da gold, porque não é uma ação.

| Tabela | Conteúdo |
|---|---|
| `bronze.b3_cotahist` | registos `01` do mercado à vista, campos do layout como texto, com auditoria; carregada por **Auto Loader** ([streaming.md](streaming.md)) |
| `silver.b3_cotacao_diaria` | SCD1 por (pregão, ticker): lote padrão (BDI 02), FII (12) e ETF e fundos (14). Preços em reais por unidade |
| `silver.cvm_valor_mobiliario` | SCD1 por ticker: CNPJ da companhia, espécie declarada e segmento de listagem, do FCA mais recente |
| `gold.dim_ativo_b3` | papel + emissor: companhia (FCA + cadastro CVM, com setor) ou FII (pelo ISIN do informe mensal) |
| `gold.fct_cotacao_diaria` | OHLC, negócios, volume, `fator_evento`, `retorno_dia` e `preco_ajustado`; incremental pelo **Change Data Feed** da silver ([streaming.md](streaming.md)) |
| `gold.vw_b3_desempenho` | último fecho, retornos (dia, 1 mês, ano, 12 meses), volume médio de 30 dias e P/VP dos FII |

### Ajuste a desdobramentos e grupamentos

> **Atualização (16/10/2026):** nas ações, o fator passou a vir dos **eventos oficiais da B3**: desdobramentos,
> grupamentos e também bonificações, que a heurística não tratava. A comparação mostrou que a heurística tinha
> falhado 38 de 105 eventos desde 2021 e todas as bonificações. Ver [fundamentos.md](fundamentos.md). A heurística
> descrita abaixo continua a ser usada em FII e ETF.

#### Heurística (FII, ETF e ações sem dados oficiais)

O COTAHIST traz o preço negociado, sem ajuste. Sem tratamento, um desdobramento 1:10 apareceria como uma queda de
90 %. A gold marca um evento quando se cumprem duas condições no mesmo pregão:

1. o fecho varia perto de um fator inteiro: 1/k num desdobramento, k num grupamento (tolerância de 8 %);
2. muda o número de distribuição do papel (`DISMES`).

Exemplos verificados: o grupamento 10:1 da MGLU3 em 27/05/2024 (de R$ 1,32 para R$ 13,15) é detetado; a queda de
77 % da Americanas em 12/01/2023 não muda a distribuição e por isso não é tratada como evento. No backfill
2021-2026 foram detetados 290 eventos.
Os eventos detetados ficam registados na regra INFO `eventos_detetados`. A regra `retorno_diario_extremo` lista
variações acima de ±50 % que sobraram, possíveis eventos que escaparam. **Dividendos e bonificações não são
ajustados:** os retornos são de preço.

## Carga

```bash
python scripts/apply_sql.py --env dev --dir sql/schemas --dir sql/dimensions --dir sql/facts --dir sql/views
python scripts/deploy_workspace.py --env dev --fonte b3 --fonte cvm
# backfill: anuais desde inicio_backfill (2021); incremental: diários dos últimos 10 dias
# (pelo ADF, ou run_now com job_parameters={"run_mode": "backfill"})
```

O FCA carrega-se com o job da CVM e `entidades=cia_aberta_fca`.

## Qualidade

| Regra | Severidade | Onde |
|---|---|---|
| `chave_unica` (pregão, ticker) | CRITICAL | silver |
| `formato_layout`: data e campos numéricos convertíveis | HIGH | bronze → silver (rejeitados vão para a quarentena) |
| `data_nao_futura` | HIGH | silver |
| `preco_positivo`, `fecho_entre_minimo_e_maximo` | INFO | silver |
| `fct_cotacao_chave_unica`, `dim_ativo_chave_unica` | CRITICAL | gold |
| `eventos_detetados`, `retorno_diario_extremo`, `acao_sem_emissor` | INFO | gold |

Frescura (`config/sla.yaml`): o watermark do último pregão não pode ter mais de 5 dias, e o `bronze_b3` tem de ter
sucesso nas últimas 96 horas.
