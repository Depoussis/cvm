# Deployment e execução (Fase 1)

## Pré-requisitos
- Azure CLI ≥ 2.60 com Bicep (`az bicep install`) e login: `az login --tenant <tenant-id>`.
- Python 3.11 e um ambiente virtual com `requirements-dev.txt`.
- Permissões: **Owner** na subscrição (os passos de RBAC exigem `Microsoft.Authorization/roleAssignments/write`).
- Os resource providers `Microsoft.Databricks`, `Microsoft.DataFactory`, `Microsoft.Storage`, `Microsoft.KeyVault`,
  `Microsoft.OperationalInsights` e `Microsoft.Insights` registados (`az provider register -n <ns> --wait`).

Em Git Bash no Windows, exportar `MSYS_NO_PATHCONV=1` antes dos comandos `az` com caminhos `/subscriptions/...`.

## 1. Infraestrutura
```bash
az group create -n rg-findata-dev -l northeurope
az deployment group what-if -g rg-findata-dev -p infrastructure/bicep/environments/dev.bicepparam
az deployment group create  -g rg-findata-dev -n fundacao-dev -p infrastructure/bicep/environments/dev.bicepparam
```
Validar: `az resource list -g rg-findata-dev -o table` mostra storage, key vault, log analytics, databricks,
access connector e data factory. O resource group gerido `rg-dbw-findata-dev-managed` não deve ter NAT Gateway.

## 2. Permissões (RBAC)
```bash
bash scripts/deploy_rbac.sh dev
```
Atribui `Storage Blob Data Contributor` ao Access Connector, ao ADF e ao utilizador administrador;
`Key Vault Secrets User` ao ADF; `Key Vault Secrets Officer` ao administrador; `Contributor` do workspace ao ADF.
A propagação pode levar alguns minutos.

## 3. Unity Catalog
```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt     # Linux/macOS: .venv/bin/pip
python scripts/setup_unity_catalog.py --env dev
```
Cria `sc_findata_dev`, as external locations `el_findata_dev_<contêiner>`, o catálogo `findata_dev`, os schemas
`bronze`, `silver`, `gold`, `control`, `ops` e os volumes `ops.raw`, `ops.checkpoints`, `ops.quarantine`.
Sem `--skip-validation`, o Databricks testa o acesso de cada external location ao ADLS (exige o passo 2).

### Grupos de conta (manual, account admin)
Na consola https://accounts.azuredatabricks.net → *User management* → *Groups*, criar `grp_findata_engineers` e
`grp_findata_analysts`, adicionar os membros e atribuir os grupos ao workspace `dbw-findata-dev`.
Depois, voltar a correr `setup_unity_catalog.py` para aplicar as permissões.

## 4. Tabelas de controlo
```bash
python scripts/apply_sql.py --env dev --dir sql/control
```
Ou, no Databricks, o notebook `notebooks/setup/01_create_control_tables.py` (widget `env`).

Validar no SQL Editor:
```sql
SHOW TABLES IN findata_dev.control;
DESCRIBE TABLE EXTENDED findata_dev.control.pipeline_execution;
```

## 5. Testes locais
```bash
python -m pytest -q
```

## Remover o ambiente
```bash
az group delete -n rg-findata-dev        # apaga também o resource group gerido do Databricks
```
O catálogo `findata_dev` fica no metastore regional e deve ser removido antes: `DROP CATALOG findata_dev CASCADE`.
