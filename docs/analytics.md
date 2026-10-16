# Analytics e consumo (Fase 6)

## Modelo dimensional (gold)

```text
              dim_data (data_key)                                  dim_serie (serie_codigo)
                 │   │   │                                              │
fct_ptax_diario ─┘   │   └── fct_serie_valor ───────────────────────────┘
   │ (simbolo)       │
dim_moeda            └── fct_fundo_diario ── dim_fundo_classe (cnpj_classe) ── fct_fundo_mensal
                                                                            dim_companhia (cd_cvm)
```

| Tabela | Grão | Linhas (16/10/2026) |
|---|---|---|
| `fct_serie_valor` | série × data | 37 303 |
| `fct_ptax_diario` | moeda × dia (fechamento) | 29 570 |
| `fct_fundo_diario` | fundo/classe × subclasse × dia | 17 876 512 |
| `fct_fundo_mensal` | fundo/classe × subclasse × mês | 874 213 |
| `dim_data`, `dim_serie`, `dim_moeda`, `dim_fundo_classe`, `dim_companhia` | — | — |

## Indicadores (vistas)

| Vista | O que responde |
|---|---|
| `vw_fundos_vs_selic` | Por mês e classificação: rentabilidade mediana e % de fundos acima da Selic acumulada no mês (SGS 4390). Filtros: classes sem subclasse, PL ≥ R$ 10 mi, ≥ 10 informes no mês, \|rentabilidade\| < 50 % |
| `vw_cambio_mensal` | PTAX de venda: média e fim de mês, variação mensal (%) |
| `vw_industria_fundos_mensal` | Somas mensais de PL, cotistas e captação líquida (**com dupla contagem de FIC**: não é o PL da indústria) |
| `vw_juros_cambio_diario` | Meta Selic, Selic anualizada e PTAX USD/EUR por dia |
| `vw_serie_ultimo_valor`, `vw_fundos_maiores_pl`, `vw_fundos_captacao_mensal` | Últimos valores e rankings |
| `vw_qualidade_resumo`, `vw_execucoes_resumo`, `vw_reapresentacoes_resumo` | Operação |

Exemplo (agosto/2026, Selic do mês 1,09 %): 59,6 % dos multimercados e 53,4 % dos fundos de renda fixa ficaram acima
da Selic; ações, 35,9 %.

## Painel no Databricks (AI/BI)

**Findata · Mercado, fundos e operação**, em `/Workspace/Shared/findata_dev`, publicado por
`scripts/deploy_dashboard.py` (definição versionada em `dashboards/findata_dev.lvdash.json`):

1. **Mercado (BCB):** Meta Selic, PTAX USD/EUR, Selic desde 2000, PTAX diária, variação mensal do câmbio, IBC-Br.
2. **Fundos (CVM):** PL e captação somados, % de fundos acima da Selic e rentabilidade mediana por classificação,
   20 maiores fundos.
3. **FII · rankings** (inspirada no StatusInvest, só com dados oficiais da CVM): FII listados, segmentos, mês de
   referência e PL somado; top 10 por cotistas, % em caixa (liquidez/PL), PL, DY no mês, DY 12 meses e
   rentabilidade 12 meses; PL e DY mediano por segmento. Ticker derivado do ISIN (`BRKNCRCTF000` → `KNCR11`).
   Fora: cotação do dia, IFIX, liquidez de pregão, comunicados e calendário (dados da B3/outras fontes).
   Notas dos dados: ~40 % dos FII informam DY = 0 todos os meses (a mediana usa só DY > 0); valores extremos
   (DY no mês > 5 %, DY 12 m > 40 %, rentabilidade 12 m fora de −90 %…+100 %) ficam fora dos rankings.
4. **Análise de fundo:** dropdown com pesquisa (≈ 26 mil FI e FII com dados recentes, formato `nome · FI|FII · CNPJ`)
   ligado ao parâmetro `:fundo` de cinco datasets: ficha, rentabilidade no mês vs Selic do mês, PL e cotistas,
   dividend yield (FII) e cota diária (FI). Abre no maior FII do grupo Itaú (Kinea Rendimentos Imobiliários,
   administrado pela Intrag).
5. **Operação e qualidade:** reconciliação (última execução por fonte), frescura, execuções e regras com falhas.

As consultas correm no SQL Warehouse serverless 2X-Small (≈ 3,20 €/h só enquanto ligado; auto-stop 1 min).

## Power BI

O ficheiro `.pbix` cria-se no Power BI Desktop; a ligação usa o conector nativo, sem copiar dados:

1. Databricks → **SQL Warehouses** → `Serverless Starter Warehouse` → **Connection details**: copiar
   *Server hostname* (`adb-7405612954969039.19.azuredatabricks.net`) e *HTTP path*.
2. Power BI Desktop → **Obter dados → Azure Databricks** → colar hostname e HTTP path; modo **DirectQuery** para as
   tabelas grandes (`fct_fundo_diario`) e **Importar** para as restantes.
3. Autenticação: **Microsoft Entra ID** (a mesma conta). Sem tokens pessoais.
4. Catálogo `findata_dev`, schema `gold`: importar as dimensões, `fct_serie_valor`, `fct_ptax_diario`,
   `fct_fundo_mensal` e as vistas `vw_*`.
5. Relações: `data_key` (factos) → `dim_data[data_key]`; `serie_codigo` → `dim_serie`; `simbolo` → `dim_moeda`;
   `cnpj_classe` → `dim_fundo_classe`. As chaves primárias e estrangeiras declaradas no Unity Catalog são lidas
   pelo Power BI como sugestão de relações.

Alternativa sem Desktop: Databricks → painel → **Share**, ou *Publish to Power BI* a partir do Catalog Explorer
(exige uma área de trabalho Power BI na mesma conta Entra ID).

## Qualidade dos dados nesta fase
Regras novas na gold da CVM: chave única de `fct_fundo_mensal` (CRITICAL), PL negativo (INFO) e rentabilidade mensal
extrema ≥ ±50 % (INFO, provável erro de cota informado pelo administrador). Primeira execução: 45 meses com PL negativo e 1 785 com rentabilidade extrema (de 839 100); a vista `vw_fundos_vs_selic` exclui estes últimos. O painel mostra todas as regras que
falharam nos últimos 14 dias.
