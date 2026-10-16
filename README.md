# Brazilian Financial Data Platform

Plataforma de engenharia de dados financeiros em Azure (arquitetura medalhão) com fontes públicas brasileiras:
Banco Central do Brasil (SGS e PTAX) e Comissão de Valores Mobiliários (dados.cvm.gov.br).
Projeto de estudo, sem vínculo com o BCB ou a CVM.

**Stack:** ADLS Gen2 · Azure Databricks (PySpark, Delta Lake, Unity Catalog) · Azure Data Factory ·
Key Vault · Log Analytics · Bicep · Python 3.11.

## Estado

| Fase | Conteúdo | Estado |
|---|---|---|
| 1. Fundação | Infraestrutura, ADLS, RBAC, Unity Catalog, repositório, tabelas de controlo | concluída (16/10/2026) |
| 2. Banco Central | SGS e PTAX: histórico e incremental, bronze/silver/gold | concluída (16/10/2026), ver [docs/pipelines_bcb.md](docs/pipelines_bcb.md) |
| 3. CVM | Catálogo, ficheiros históricos, ZIP, fundos e companhias abertas | concluída (16/10/2026), ver [docs/pipelines_cvm.md](docs/pipelines_cvm.md) |
| 4. Histórico e auditoria | SCD1, SCD2, hashes, watermarks, reapresentações, reconciliação | concluída (16/10/2026), ver [docs/auditoria.md](docs/auditoria.md) |
| 5. Orquestração | ADF, Databricks Jobs, retries, alertas, agendamentos | — |
| 6. Qualidade e analytics | Testes de dados, modelo dimensional, indicadores, Power BI | — |
| 7. Produção | CI/CD, segurança, documentação, monitorização, custos, DR | — |

## Estrutura

```text
infrastructure/bicep/     main.bicep, módulos e parâmetros por ambiente
config/environments/      configuração por ambiente (sem segredos)
src/common/               configuração, HTTP com retries, raw, janelas, utilitários SQL
src/ingestion/            clientes das APIs (bcb_sgs, bcb_ptax) e ficheiros CVM (contrato, ZIP, codificação)
src/bronze|silver|scd/    escrita bronze, MERGE SCD1/SCD2
src/quality/              regras de qualidade
src/audit/                execuções, watermarks e registo de ficheiros nas tabelas de controlo
sql/                      DDL: control, schemas (bronze/silver), dimensions, facts, views
notebooks/                setup, bronze, silver e gold (formato fonte do Databricks)
scripts/                  deploy de RBAC, setup do Unity Catalog, aplicação de SQL
tests/unit/               testes sem Spark (pytest); integração com Spark em notebooks/tests/integracao.py
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
python -m pytest -q
```

Custos: [docs/cost_estimation.md](docs/cost_estimation.md). Decisões: [docs/architecture.md](docs/architecture.md).
