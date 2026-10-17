# CI/CD (Fase 7)

Desde 17/10/2026 o CI/CD corre no **GitHub Actions**, no mesmo repositório (`Depoussis/cvm`). O Azure DevOps
(`azure-pipelines.yml`, mais abaixo) continua definido, mas parado: a organização nova não tem execuções gratuitas
até a Microsoft aprovar o pedido de paralelismo. Os passos e os scripts são os mesmos nos dois.

```text
push / pull request ──► ci.yml: pytest (sem Spark nem rede) · compilação Bicep
push em main ────────► cd.yml (só se mudar código, SQL, config ou pipelines):
                         ci.yml → apply_sql (tabelas/vistas) → deploy_workspace (código e jobs Databricks)
                         → deploy_adf (linked service, pipelines, gatilhos) → deploy_dashboard
                         → smoke_test (testes de integração no Databricks)
dias úteis 23:00 ───► exportar_painel.yml (snapshot do painel, branch painel-dados)
domingo 07:00 ──────► validar_fontes.yml (validação contra fontes externas; falha = alerta por e-mail)
```

| Workflow | Identidade (OIDC, sem segredos) | Permissões |
|---|---|---|
| `ci.yml` | nenhuma | só leitura do repositório |
| `cd.yml` | aplicação de deploy `27dd81ac-…` (a mesma da service connection `sc-findata-dev`) | Contributor em `rg-findata-dev`, permissões de deploy no Unity Catalog |
| `exportar_painel.yml`, `validar_fontes.yml` | `findata-painel-github` (`40452b47-…`) | só leitura no catálogo, `CAN_USE` no SQL Warehouse |

O deploy não muda agendamentos (gatilhos do ADF iniciados ficam iniciados, jobs mantêm a pausa), nem o dono das
execuções e o e-mail de alertas dos jobs existentes: `deploy_workspace.py` reaproveita-os do job atual quando não há
`FINDATA_ALERT_EMAIL` / `FINDATA_RUN_AS`.

### Passo único: credencial federada da aplicação de deploy
O GitHub só obtém token para a aplicação de deploy se ela confiar no branch `main` deste repositório. O subject
usa os identificadores numéricos do dono e do repositório (formato dos repositórios novos do GitHub):

```bash
az ad app federated-credential create --id 27dd81ac-d529-4b9d-910a-0108ea25f5b2 --parameters '{"name":"github-cvm-main","issuer":"https://token.actions.githubusercontent.com","subject":"repo:Depoussis@288774958/cvm@1422145072:ref:refs/heads/main","audiences":["api://AzureADTokenExchange"]}'
```

No workspace Databricks, a identidade tem de estar no grupo **admins** e ter os direitos *Workspace access* e
*Databricks SQL access* (Settings → Identity and access). Com Contributor no resource group, isso acontece sozinho
no primeiro login pelo portal. Aqui não aconteceu, porque a identidade foi registada por código para receber antes
as permissões do Unity Catalog. Feito à mão em 17/10/2026. O deploy precisa de ser administrador para atualizar
jobs de outro dono, publicar em `/Workspace/Shared` e publicar o painel AI/BI.

Sem a credencial federada, o `cd.yml` falha no passo "Login no Azure" (os testes correm na mesma). O `cd.yml` não usa
`environment:` porque isso mudaria o subject do token.

# Azure DevOps (alternativa, parada)

Organização **felipecoelho05**, projeto **findata**; código em GitHub `Depoussis/cvm`; definição em
`azure-pipelines.yml`.

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
