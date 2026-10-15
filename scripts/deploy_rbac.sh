#!/usr/bin/env bash
# Atribui as funções RBAC da plataforma (infrastructure/bicep/modules/rbac.bicep).
# Exige Owner ou User Access Administrator na subscrição. Uso:
#   bash scripts/deploy_rbac.sh [ambiente]      (por omissão: dev)
set -euo pipefail
export MSYS_NO_PATHCONV=1  # Git Bash no Windows: não converter caminhos /subscriptions/...

ENV="${1:-dev}"
RG="rg-findata-${ENV}"
AZ="${AZ_CLI:-az}"
command -v "$AZ" >/dev/null 2>&1 || AZ="C:/Users/felip/.azcli/Scripts/az.bat"
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"

saida() { "$AZ" deployment group show -g "$RG" -n "fundacao-${ENV}" --query "properties.outputs.$1.value" -o tsv | tr -d '\r'; }

ADMIN_ID="$("$AZ" ad signed-in-user show --query id -o tsv | tr -d '\r')"

"$AZ" deployment group create -g "$RG" -n "rbac-${ENV}" \
  -f "$RAIZ/infrastructure/bicep/modules/rbac.bicep" \
  -p storageName="$(saida storageAccountName)" \
     keyVaultName="$(saida keyVaultName)" \
     databricksWorkspaceName="$(saida databricksWorkspaceName)" \
     accessConnectorPrincipalId="$(saida accessConnectorPrincipalId)" \
     dataFactoryPrincipalId="$(saida dataFactoryPrincipalId)" \
     adminPrincipalId="$ADMIN_ID" adminPrincipalType=User \
  --query "properties.provisioningState" -o tsv
