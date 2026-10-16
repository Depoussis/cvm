# CI/CD no Azure DevOps (Fase 7)

Organização **felipecoelho05**, projeto **findata**; código em GitHub `Depoussis/cvm`; definição em
`azure-pipelines.yml`.

```text
push / pull request ──► CI: pytest (44 testes, sem Spark nem rede) · compilação Bicep · JSON do ADF · painel
push em main ────────► CD (ambiente findata-dev):
                         apply_sql (tabelas/vistas) → deploy_workspace (código e jobs Databricks)
                         → deploy_adf (linked service, pipelines, gatilhos) → deploy_dashboard
                         → smoke_test (testes de integração no Databricks)
```

## Decisões
- **Azure DevOps a ler do GitHub** (pedido do projeto): o código fica no GitHub; o Azure Pipelines é o motor de
  CI/CD dentro do Azure. Alternativa: GitHub Actions (mesmos scripts, outra sintaxe).
- **Federação de identidade (OIDC)** na service connection: o Azure DevOps recebe um token de curta duração; não
  existe segredo de aplicação guardado nem a expirar.
- **Os scripts de deploy são os mesmos que se usam à mão.** O pipeline só os encadeia.
- **O CD não altera agendamentos:** os gatilhos do ADF iniciados não são tocados e os jobs mantêm o estado de pausa.
- **Infraestrutura (Bicep):** o CI compila; o deploy da infraestrutura continua manual (`az deployment group
  create …`), porque altera recursos com custo e permissões (RBAC).

## Passos únicos (feitos por quem administra a subscrição)

### 1. Service connection
Project settings → **Service connections** → **New** → **Azure Resource Manager** →
*Identity type*: **App registration (automatic)**, *Credential*: **Workload identity federation** →
*Scope level*: **Subscription**, subscrição do Free Trial, *Resource group*: **rg-findata-dev** →
*Service connection name*: **`sc-findata-dev`** → marcar *Grant access permission to all pipelines* → **Save**.

Isto cria uma aplicação no Entra ID com o papel **Contributor no resource group**. Chega para o ADF e para o
workspace Databricks (quem tem Contributor no workspace entra como administrador na primeira chamada).

Verificar depois de criar (16/10/2026, a primeira tentativa ficou no resource group errado `NetworkWatcherRG`):
```bash
az role assignment list --assignee <client id> --all -o table   # tem de mostrar Contributor em rg-findata-dev
```

### 2. Permissões no Unity Catalog
A identidade só aparece no Databricks depois do primeiro acesso; para dar permissões antes disso, registá-la no
workspace (Settings → Identity and access → Service principals → Add, com o client id) ou pelo SDK
(`w.service_principals.create(application_id=...)`).
Na service connection → **Manage App registration** → copiar o **Application (client) ID** e correr, como dono do
catálogo:
```bash
python scripts/apply_sql.py --env dev --dir sql/grants --var sp=<client id>
```

### 3. Capacidade de execução
Organizações novas não têm execuções gratuitas em agentes da Microsoft até a Microsoft aprovar o pedido
(https://aka.ms/azpipelines-parallelism-request, 2–3 dias úteis). Alternativa imediata: agente próprio
(*Project settings → Agent pools → Default → New agent*) e trocar `vmImage: ubuntu-latest` por `name: Default`.

### 4. Pipeline
Pipelines → **New pipeline** → **GitHub (YAML)** → autorizar a app *Azure Pipelines* no GitHub → repositório
`Depoussis/cvm` → **Existing Azure Pipelines YAML file** → `/azure-pipelines.yml` → **Variables**:
`alertEmail` e `runAs` = e-mail do responsável (ficam fora do repositório público) → **Run**.

O ambiente `findata-dev` é criado na primeira execução; para exigir aprovação antes do deploy:
Pipelines → Environments → findata-dev → **Approvals and checks**.
