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

## Painel público em Streamlit

Publicado em **https://findata-depoussis.streamlit.app** (repositório `Depoussis/cvm`, `app/streamlit_app.py`).
Visual clean (claro/escuro). **Navegação no topo** (`st.navigation(position="top")`), sem barra lateral:

| Menu | Página | Conteúdo |
|---|---|---|
| Mercado | `paginas/mercado.py` | Selic, PTAX (período e moedas), câmbio mensal, IBC-Br, índices B3 (IBOV, IFIX, SMLL, IDIV), taxas do Tesouro Direto ([pipelines_mercado.md](pipelines_mercado.md)) |
| Bolsa | `paginas/acoes.py` | ações, FII e ETF: rankings, evolução, setores, tabela com DY, P/L, P/VP e ROE, dividendos por ano |
| Simulador ▸ Um papel | `paginas/simulador.py` | compra numa data ao preço da época: eventos, proventos, IR da venda, total líquido ([simulador.md](simulador.md)) |
| Simulador ▸ Carteira com aportes | `paginas/carteira.py` | vários papéis com pesos, aportes mensais, TIR, ganho acima do IPCA, CDI e BOVA11 com os mesmos aportes ([simulador.md](simulador.md#carteira-com-aportes-menu-simulador--carteira-com-aportes)) |
| Modelo | `paginas/modelo.py` | backtest, comparação de modelos, IC, importância das variáveis, ranking atual ([modelo_preditivo.md](modelo_preditivo.md)) |
| Fundos ▸ Fundos de investimento | `paginas/fundos.py` | PL, captação, maiores fundos |
| Fundos ▸ Fundos imobiliários | `paginas/fii.py` | rankings de FII (cotistas, PL, caixa, DY), segmentos |
| Fundos ▸ Análise de fundo | `paginas/analise.py` | pesquisa por nome, ticker ou CNPJ; rentabilidade contra a Selic |
| Plataforma ▸ Operação e qualidade | `paginas/operacao.py` | reconciliação, frescura, execuções, regras de qualidade |

A faixa por baixo do menu mostra a data do snapshot e as fontes. Código em `app/` (`streamlit_app.py`, `paginas/`,
`painel/`); tema em `.streamlit/config.toml`.

**Dados:** a app não liga ao Databricks. `scripts/exportar_painel.py` corre as consultas do painel AI/BI (as mesmas
de `deploy_dashboard.py`), mais o histórico mensal por fundo, as cotações e os proventos da B3 (papéis com volume ≥ R$ 300 mil/dia), os dividendos anuais e as tabelas do modelo (`ml_*`). Grava `app/dados/*.parquet` (≈ 17 MB, zstd).
Vantagens: sem segredos no Streamlit Cloud, sem warehouse ligado a cada visita, páginas rápidas. Custo: os dados
são um snapshot, atualizado uma vez por dia útil.

### Atualização automática

```
ADF pl_findata_diario (21:15)  →  GitHub Action "Exportar painel" (23:00 seg–sex, dom 08:00)
                                    exportar_painel.py → push -f do branch painel-dados (só os parquet)
                                  →  Streamlit (app/painel/dados.py) consulta o _meta.json remoto de 30 em 30 min
                                     e descarrega o snapshot se for mais novo; se falhar, usa app/dados/
```

- **Workflow:** `.github/workflows/exportar_painel.yml`, também corre à mão (Actions → Exportar painel → Run
  workflow). O resumo da execução lista as linhas de cada tabela.
- **Branch `painel-dados`:** um único commit, substituído a cada exportação. O `main` não cresce 17 MB por dia;
  `app/dados/` no `main` fica como snapshot de reserva e para desenvolvimento local.
- **Autenticação sem segredos:** a aplicação Entra `findata-painel-github` tem uma credencial federada só para
  `repo:Depoussis/cvm:ref:refs/heads/main`; o GitHub entra no Azure com OIDC (`azure/login`, sem subscrição) e o
  `exportar_painel.py` usa esse login (`auth_type="azure-cli"`). Permissões: `SELECT` no catálogo
  (`sql/grants_painel/`), `CAN_USE` no SQL Warehouse e o direito `databricks-sql-access`.
- **Custo:** ~1 min de SQL Warehouse serverless por exportação; minutos do GitHub Actions gratuitos (repositório
  público).

Passos únicos (dono do catálogo, já feitos em dev):
```bash
az ad app create --display-name findata-painel-github --sign-in-audience AzureADMyOrg   # → appId
az ad sp create --id <appId>
az ad app federated-credential create --id <appId> --parameters \
  '{"name":"github-main","issuer":"https://token.actions.githubusercontent.com",
    "subject":"repo:Depoussis@288774958/cvm@1422145072:ref:refs/heads/main","audiences":["api://AzureADTokenExchange"]}'
# o GitHub envia o subject com os IDs do dono e do repositório (formato imutável); com só os nomes, o login falha
# com AADSTS700213 e a mensagem mostra o subject certo
python scripts/configurar_painel_sp.py --env dev --client-id <appId>
python scripts/apply_sql.py --env dev --dir sql/grants_painel --var sp=<appId>
# e AZURE_CLIENT_ID=<appId> em .github/workflows/exportar_painel.yml (identificador, não é segredo)
```

Manualmente, a partir do portátil:
```bash
python scripts/exportar_painel.py --env dev     # ~30 s de warehouse, grava app/dados/
streamlit run app/streamlit_app.py              # local, na raiz do repositório (FINDATA_DADOS_URL="" ignora o remoto)
# alterações em app/painel/*.py (módulos importados) exigem "Manage app → Reboot app" no Streamlit Cloud
```

Diferenças face ao AI/BI: a cota diária dos FI (17,7 M linhas) não vai no snapshot; a análise mostra a
rentabilidade acumulada a partir das rentabilidades mensais, comparada com a Selic acumulada.

Só no Streamlit existem as páginas **Bolsa**, **Simulador** e **Modelo**. A Bolsa (B3, ver
[pipelines_b3.md](pipelines_b3.md) e [fundamentos.md](fundamentos.md)) é alimentada por `gold.vw_b3_desempenho`, pelo
histórico diário ajustado, por `vw_b3_dividendos_anuais` e pelos fundamentos do modelo. Tem:
- indicadores do Ibovespa (via BOVA11) e altas/baixas do dia;
- rankings por classe (ações, FII, ETF), setor e liquidez mínima: dia, volume, 12 meses, maior DY (ações) e menor
  P/VP (FII);
- evolução do preço em base 100 de até 6 papéis;
- retorno mediano por setor;
- tabela pesquisável de todos os papéis, com DY 12m, P/L, P/VP e ROE nas ações;
- dividendos e JCP por ano de cada ação (R$ por ação ajustado e DY do ano).

**Publicar (uma vez):** share.streamlit.io → *Create app* → *Deploy a public app from GitHub* → repositório
`Depoussis/cvm`, branch `main`, ficheiro `app/streamlit_app.py` → *Advanced settings*: Python 3.11 → *Deploy*.
As dependências vêm de `app/requirements.txt`.

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
