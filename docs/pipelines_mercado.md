# Pipeline de referências de mercado: índices B3 e Tesouro Direto

Job **`findata_dev_mercado`** (serverless), disparado pelo ADF no `pl_findata_diario` em paralelo com BCB, CVM e
B3; a frescura só corre se os quatro tiverem sucesso. Configuração em `config/datasets/mercado.yaml`, funções puras
em `src/ingestion/mercado.py` (testes em `tests/unit/test_mercado.py`).

```
bronze_mercado → silver_mercado → gold_mercado
```

## Fontes (confirmadas em 16/10/2026)

| Entidade | Fonte | Formato | Carga |
|---|---|---|---|
| `indices_b3` | API pública das estatísticas de índices da B3 (`IndexCall/GetPortfolioDay`, parâmetros em base64) | JSON: matriz dia (1–31) × mês (1–12) por índice e ano, números `131.147,29` | primeira carga e `backfill`: desde 2015; incremental: ano corrente e anterior (8 pedidos) |
| `tesouro_direto` | Tesouro Transparente, "Preços e taxas históricas" | CSV `;`, ~15 MB, ~177 mil linhas desde 2002, decimais com vírgula | o CSV inteiro vai sempre para o volume; para a bronze, só as linhas com data base desde o watermark − 15 dias (tudo na primeira carga). Ficheiro igual a um já processado (mesmo hash) é ignorado |

Índices carregados: **IBOV** (Ibovespa), **IFIX** (fundos imobiliários), **SMLL** (small caps), **IDIV**
(dividendos). Para acrescentar um, basta pôr o código em `indices_b3.indices` e correr em `backfill`. São índices
de **retorno total**, com proventos reinvestidos.

O Tesouro publica de manhã os valores do dia útil anterior. A API da B3 já tem o fecho do dia à noite.

## Tabelas

| Camada | Tabela | Chave | Notas |
|---|---|---|---|
| bronze | `b3_indice_dia` | — | texto como recebido (índice, ano, mês, dia, valor) |
| bronze | `tesouro_preco_taxa` | — | texto como recebido |
| silver | `b3_indice_diario` (SCD1) | índice, data | regra INFO `salto_indice` (variação diária > 15 %) |
| silver | `tesouro_preco_taxa` (SCD1) | título, vencimento, data base | preço a zero na fonte → NULL (regra INFO `pu_sem_valor`); preço negativo → HIGH |
| gold | `fct_indice_diario` | índice, data | nome do índice e retorno diário; regra INFO `ibov_alinhado_cotahist` |
| gold | `fct_tesouro_diario` | título, vencimento, data base | nome como no site ("Tesouro IPCA+ 2035"), indexador (IPCA, Selic, Prefixado, IGP-M), juros semestrais |

DDL: `sql/schemas/14_mercado_bronze.sql`, `sql/schemas/27_mercado_silver.sql`, `sql/facts/48_mercado.sql`.
Frescura: `config/sla.yaml`, `padrao_dias.mercado = 5`, `execucao_max_horas.bronze_mercado = 96`.

Defeito da fonte encontrado na primeira carga: o Tesouro Prefixado com Juros Semestrais 2021 tem PU de compra,
venda e base a 0,00 em 29 dias entre 22/01/2010 e 05/03/2010, mas tem taxa. A gold ficou bloqueada pela regra
`pu_positivo` até a silver passar a tratar preço zero como "sem preço".

Primeira carga (16/10/2026): 2 927 pregões por índice (02/01/2015 a 16/10/2026); 177 434 linhas do Tesouro em
8 tipos de título (31/12/2004 a 15/10/2026).

## No painel

- **Mercado:** índices em base 100 (escolha de índices e período), tabela de rentabilidade (dia, ano, 12 meses,
  5 anos), taxas de compra de hoje de todos os títulos à venda e a evolução das taxas dos títulos escolhidos.
- **Simulador → Carteira com aportes:** comparação com os mesmos aportes num título do Tesouro Direto sem cupões
  (compra ao PU de compra do dia, valor ao PU de recompra, IR regressivo por aporte, sem custódia da B3) e no
  Ibovespa e no IFIX oficiais (retorno total, sem custos nem IR).

Snapshot: `indices_b3` (~12 mil linhas) e `tesouro` (desde 2015, ~101 mil linhas).
