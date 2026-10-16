# Arquitetura

Estado em 16/10/2026: fases 1 a 6 concluídas, mais B3, streaming, fundamentos, modelo preditivo e simulador (ver o README). O diagrama mostra o estado atual.

## Visão lógica

```text
             Fontes públicas                     Orquestração                    Consumo
  ┌──────────────────────────────┐        ┌──────────────────────┐      ┌───────────────────────┐
  │ BCB SGS (REST JSON)          │        │ Azure Data Factory    │      │ Databricks SQL        │
  │ BCB PTAX (OData JSON)        │        │  agenda, parâmetros,  │      │ (serverless 2X-Small) │
  │ CVM dados.cvm.gov.br (CSV/ZIP)│       │  dependências, alertas│      │ AI/BI dashboard       │
  │  FI, FII, cadastros, FCA,    │        └──────────┬───────────┘      │ Streamlit Cloud       │
  │  DFP/ITR                     │                   │                  │  (snapshot parquet)   │
  │ B3 COTAHIST (TXT largura fixa)│                  │                  │ MLflow / modelo UC    │
  │ B3 empresas listadas (JSON)  │                   │                  └──────────▲────────────┘
  └──────────────┬───────────────┘                   │                             │
                 │ download (Python no Databricks)   │ dispara jobs                 │
                 ▼                                   ▼                              │
  ┌─────────────────────────── ADLS Gen2 (stfindatadev…) + Unity Catalog (findata_dev) ───────────┐
  │ raw/        ficheiros e payloads originais, imutáveis      → volume  findata_dev.ops.raw       │
  │ bronze/     Delta, dados como recebidos + colunas _audit   → schema  findata_dev.bronze        │
  │ silver/     Delta, tipado, deduplicado, SCD1/SCD2          → schema  findata_dev.silver        │
  │ gold/       Delta, dimensões, factos e indicadores         → schema  findata_dev.gold ─────────┘
  │ control/    execuções, watermarks, qualidade, ficheiros    → schema  findata_dev.control       │
  │ quarantine/ payloads inválidos                             → volume  findata_dev.ops.quarantine│
  │ checkpoints/                                               → volume  findata_dev.ops.checkpoints│
  └────────────────────────────────────────────────────────────────────────────────────────────────┘
        Logs de ADF, Databricks e Key Vault → Log Analytics (log-findata-dev) → alertas

Jobs Databricks (serverless, agendados pelo ADF): `findata_dev_bcb`, `findata_dev_cvm` (inclui FCA, DFP/ITR e
`gold_fundamentos`), `findata_dev_b3` (COTAHIST com Auto Loader + gold por Change Data Feed),
`findata_dev_b3_proventos` (semanal), `findata_dev_ml` (semanal), `findata_dev_frescura`, `findata_dev_auditoria`.
Documentos por tema: [pipelines_bcb.md](pipelines_bcb.md), [pipelines_cvm.md](pipelines_cvm.md),
[pipelines_b3.md](pipelines_b3.md), [streaming.md](streaming.md), [fundamentos.md](fundamentos.md),
[modelo_preditivo.md](modelo_preditivo.md), [analytics.md](analytics.md), [simulador.md](simulador.md),
[testes.md](testes.md), [conceitos.md](conceitos.md).
```

## Recursos físicos (dev)

| Recurso | Nome | Notas |
|---|---|---|
| Resource group | `rg-findata-dev` (North Europe) | um por ambiente |
| ADLS Gen2 | `stfindatadev73r4pl` | LRS, HNS, TLS 1.2, sem acesso público a blobs, **sem chaves de conta** (só Entra ID), soft delete 7 dias |
| Databricks | `dbw-findata-dev` (Premium) | Unity Catalog ativo, metastore regional `metastore_azure_northeurope` |
| Access Connector | `ac-findata-dev` | identidade gerida usada pela storage credential `sc_findata_dev` |
| Data Factory | `adf-findata-dev-73r4pl` | identidade gerida; logs dedicados no Log Analytics |
| Key Vault | `kv-findata-dev-73r4pl` | RBAC, soft delete 7 dias |
| Log Analytics | `log-findata-dev` | retenção 30 dias, quota diária de 1 GB |
| SQL Warehouse | `Serverless Starter Warehouse` | reduzido para 2X-Small, auto-stop 1 min |

Infraestrutura em `infrastructure/bicep`; Unity Catalog em `scripts/setup_unity_catalog.py`; tabelas de controlo em `sql/control`.

## Estrutura de diretórios no ADLS

Os contêineres separam a finalidade; dentro de cada um, a hierarquia segue fonte → entidade → data.
Os ambientes ficam em contas de armazenamento diferentes (um resource group por ambiente), o que isola
permissões e custos melhor do que uma pasta `env=` dentro da mesma conta.

```text
raw/            <fonte>/<entidade>/ingestion_date=AAAA-MM-DD/<pipeline_run_id>/<ficheiro original>
                ex.: raw/bcb_sgs/serie_432/ingestion_date=2026-10-16/<run>/sgs_432_2000-01-01_2009-12-31.json
                ex.: raw/cvm/fi_doc_inf_diario/ingestion_date=2026-10-16/<run>/inf_diario_fi_202401.zip
quarantine/     <fonte>/<entidade>/ingestion_date=AAAA-MM-DD/<pipeline_run_id>/<ficheiro> + motivo.json
checkpoints/    <fonte>/<entidade>/<camada>/
bronze|silver|gold|control/tables/   tabelas Delta geridas pelo Unity Catalog (caminhos internos do UC)
control/_catalog/                    localização gerida do catálogo
```

As tabelas Delta são **geridas** pelo Unity Catalog: o nome lógico (`findata_dev.silver.…`) é o contrato,
e o UC decide a pasta física dentro da localização do schema. Isso dá lineage, permissões e
`DROP`/`UNDROP` consistentes. Os ficheiros originais ficam fora das tabelas, no volume `ops.raw`.

## Decisões de arquitetura

### 1. Bicep (Azure) + scripts Python com o SDK do Databricks (Unity Catalog)
- **Alternativas:** Terraform para tudo (providers `azurerm` + `databricks`); Bicep + Terraform.
- **Escolha:** Bicep para os recursos Azure, porque não precisa de ficheiro de estado (o estado é o próprio
  Azure) nem de backend remoto, e vem com o Azure CLI. O Bicep não gere objetos dentro do Databricks, por isso
  o Unity Catalog é configurado por `scripts/setup_unity_catalog.py`, que é idempotente e usa o SDK oficial.
- **Quando mudar:** com várias equipas e muitos objetos UC (grants por tabela, clusters policies, jobs), o
  provider Terraform `databricks` passa a compensar. A pasta `infrastructure/terraform` fica reservada.

### 2. Databricks Premium (não trial)
O Unity Catalog exige Premium. O tier `trial` (DBUs gratuitos 14 dias) **é recusado em subscrições Azure Free
Trial** (erro `TrialSkuNotSupportedForSubscriptionType`, verificado no deploy).

### 3. Sem Secure Cluster Connectivity em dev (`enableNoPublicIp = false`)
Com a VNet gerida por omissão, ligar o SCC cria um NAT Gateway, que cobra por hora mesmo sem clusters.
Em dev os nós têm IP público com NSG gerido pelo Databricks. Verificado após o deploy: o resource group gerido
não tem NAT Gateway nem IPs públicos. **Produção:** VNet injection + SCC + private endpoints.

### 4. Computação limitada pela quota da subscrição
A subscrição Free Trial tem **4 vCPUs por região**. Isso permite apenas um cluster de 1 nó (ex.: `Standard_DS3_v2`,
4 vCPU / 14 GB) por vez, e impede SQL Warehouses clássicos. Por isso:
- Jobs: cluster de jobs single-node, criado e destruído por execução.
- SQL e Power BI: SQL Warehouse **serverless** (não usa quota da subscrição), 2X-Small, auto-stop 1 min.
- Volume esperado (BCB: milhares de linhas; CVM: dezenas de milhões de linhas no informe diário de fundos)
  cabe num nó de 14 GB com processamento por ficheiro/mês.

### 5. Ingestão em Python no Databricks; ADF só orquestra
- **Alternativa:** cópias do ADF (HTTP → ADLS) para os ficheiros.
- **Escolha:** o download corre em Python (`src/ingestion`) dentro do job do Databricks, porque o projeto exige
  hash por ficheiro, deteção de versões, retries com backoff, extração de ZIP e quarentena — lógica que no ADF
  ficaria espalhada por várias atividades. O ADF agenda, passa parâmetros (`env`, `run_mode`, datas), encadeia
  dependências e concentra a monitorização. Também evita pagar duas vezes (cópia ADF + cluster).

### 6. Ambientes
Catálogos `findata_dev`, `findata_test`, `findata_prod`, cada um com os mesmos schemas, num resource group e conta
de armazenamento próprios. Em dev só existe `findata_dev`; test e prod são criados com os mesmos Bicep/scripts
(`environments/<env>.bicepparam`, `config/environments/<env>.yaml`).

### 7. Identidades e permissões
- Unity Catalog → ADLS: Access Connector (`Storage Blob Data Contributor` na conta).
- ADF → ADLS e Key Vault: identidade gerida (`Storage Blob Data Contributor`, `Key Vault Secrets User`).
- ADF → Databricks: identidade gerida com `Contributor` no workspace (exigido pelo linked service com MSI).
- Grupos de conta `grp_findata_engineers` (escrita em todas as camadas) e `grp_findata_analysts`
  (leitura da gold). Os grupos de conta só podem ser criados na consola de conta do Databricks por um account admin
  (ver `docs/deployment.md`); o script de setup aplica as permissões assim que os grupos existirem.
- Sem segredos no código: todas as fontes são públicas e a autenticação é Entra ID.

## Limitações conhecidas da fundação
- Sem private endpoints nem firewall de rede no ADLS e no Key Vault em dev (acesso controlado por Entra ID/RBAC).
- Log Analytics com quota de 1 GB/dia: ao atingir, os logs param até ao dia seguinte.
- Validação das external locations (16/10/2026): READ, LIST, WRITE, DELETE e PATH_EXISTS passam nos 7 contêineres.
  O teste opcional de *file events* falha (o Access Connector não tem permissões de Event Grid/filas); não é usado,
  porque a ingestão lê ficheiros por lista explícita, não por Auto Loader em modo notificação.
- Os testes de `src/audit/control.py` com Spark correm no Databricks (fase 4); localmente só há testes sem Spark.
