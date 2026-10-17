# Brazilian Financial Data Platform

Plataforma de engenharia de dados financeiros em Azure (arquitetura medalhão) com fontes públicas brasileiras:
Banco Central do Brasil (SGS e PTAX), Comissão de Valores Mobiliários (dados.cvm.gov.br) e B3 (séries históricas
de cotações, COTAHIST). Projeto de estudo, sem vínculo com o BCB, a CVM ou a B3.

**Stack:** ADLS Gen2 · Azure Databricks (PySpark, Delta Lake, Unity Catalog) · Azure Data Factory ·
Key Vault · Log Analytics · Bicep · Python 3.11.

## Estado

| Fase | Conteúdo | Estado |
|---|---|---|
| 1. Fundação | Infraestrutura, ADLS, RBAC, Unity Catalog, repositório, tabelas de controlo | concluída (16/10/2026) |
| 2. Banco Central | SGS e PTAX: histórico e incremental, bronze/silver/gold | concluída (16/10/2026), ver [docs/pipelines_bcb.md](docs/pipelines_bcb.md) |
| 3. CVM | Catálogo, ficheiros históricos, ZIP, fundos e companhias abertas | concluída (16/10/2026), ver [docs/pipelines_cvm.md](docs/pipelines_cvm.md) |
| 3b. B3 | Cotações da bolsa (ações, FII, ETF), ticker → companhia pelo FCA da CVM, ajuste a desdobramentos | concluída (16/10/2026), ver [docs/pipelines_b3.md](docs/pipelines_b3.md) |
| 3c. Streaming | Auto Loader na bronze e Change Data Feed na gold da B3 (`availableNow`, checkpoints, escrita idempotente) | concluída (16/10/2026), ver [docs/streaming.md](docs/streaming.md), [casos de teste](docs/testes.md) e [conceitos](docs/conceitos.md) |
| 3d. Fundamentos e proventos | DFP/ITR da CVM (receita, lucro, PL, dívida por trimestre); dividendos, JCP e eventos oficiais da B3 | concluída (16/10/2026), ver [docs/fundamentos.md](docs/fundamentos.md) |
| 6b. Modelo preditivo | Ranking de ações para o mês seguinte: features point-in-time, walk-forward, backtest, MLflow | experimental (16/10/2026), ver [docs/modelo_preditivo.md](docs/modelo_preditivo.md) |
| 6c. Simulador | Compra numa data ao preço da época: valorização, proventos, eventos (desdobramentos, bonificações) vs Selic e Ibovespa | concluída (16/10/2026), ver [docs/simulador.md](docs/simulador.md) |
| 6d. Carteira com aportes | Vários papéis com pesos e aportes mensais: TIR, ganho acima do IPCA, CDI e BOVA11 com os mesmos aportes; IPCA e CDI do BCB | concluída (16/10/2026), ver [docs/simulador.md](docs/simulador.md) |
| 4b. Referências de mercado | Índices oficiais da B3 (IBOV, IFIX, SMLL, IDIV) e preços/taxas do Tesouro Direto; no painel e no simulador | concluída (16/10/2026), ver [docs/pipelines_mercado.md](docs/pipelines_mercado.md) |
| 6e. Atualização automática | GitHub Action (OIDC, sem segredos) exporta o snapshot às 23:00 para o branch `painel-dados`; o Streamlit lê-o sozinho | concluída (16/10/2026), ver [docs/analytics.md](docs/analytics.md) |
| 4. Histórico e auditoria | SCD1, SCD2, hashes, watermarks, reapresentações, reconciliação | concluída (16/10/2026), ver [docs/auditoria.md](docs/auditoria.md) |
| 5. Orquestração | ADF, Databricks Jobs, retries, alertas, agendamentos | concluída (16/10/2026), ver [docs/orquestracao.md](docs/orquestracao.md) |
| 6. Qualidade e analytics | Testes de dados, modelo dimensional, indicadores, Power BI | concluída (16/10/2026), ver [docs/analytics.md](docs/analytics.md) |
| 7. Produção | CI/CD, segurança, documentação, monitorização, custos, DR | em curso: CI/CD no Azure DevOps ([docs/cicd.md](docs/cicd.md)) |

## Estrutura

```text
infrastructure/bicep/     main.bicep, módulos e parâmetros por ambiente
config/environments/      configuração por ambiente (sem segredos)
src/common/               configuração, HTTP com retries, raw, janelas, utilitários SQL
src/ingestion/            clientes das APIs (bcb_sgs, bcb_ptax), ficheiros CVM (contrato, ZIP, codificação) e B3 (layout COTAHIST)
src/bronze|silver|scd/    escrita bronze, MERGE SCD1/SCD2
src/quality/              regras de qualidade
src/audit/                execuções, watermarks e registo de ficheiros nas tabelas de controlo
sql/                      DDL: control, schemas (bronze/silver), dimensions, facts, views
notebooks/                setup, bronze, silver e gold (formato fonte do Databricks)
scripts/                  deploy de RBAC, Unity Catalog, SQL, workspace/jobs Databricks e ADF
pipelines/azure_data_factory/  linked service, pipelines e gatilhos do ADF (JSON)
tests/unit/               testes sem Spark (pytest); integração com Spark em notebooks/tests/integracao.py
app/                      painel público em Streamlit (lê o snapshot app/dados/*.parquet)
docs/                     arquitetura, custos, deployment
```

## Começar

Ver [docs/deployment.md](docs/deployment.md). Resumo:

```bash
az deployment group create -g rg-findata-dev -n fundacao-dev -p infrastructure/bicep/environments/dev.bicepparam
bash scripts/deploy_rbac.sh dev
python scripts/setup_unity_catalog.py --env dev
python scripts/apply_sql.py --env dev --dir sql/control --dir sql/schemas --dir sql/dimensions --dir sql/facts --dir sql/views
python scripts/deploy_workspace.py --env dev --run backfill
python scripts/deploy_adf.py --env dev          # ADF: linked service, pipelines, gatilhos (parados)
python scripts/deploy_dashboard.py --env dev    # painel AI/BI no Databricks
python scripts/exportar_painel.py --env dev     # snapshot do painel Streamlit (app/)
python -m pytest -q
```

Custos: [docs/cost_estimation.md](docs/cost_estimation.md). Decisões: [docs/architecture.md](docs/architecture.md).
