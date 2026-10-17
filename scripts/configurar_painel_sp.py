"""Regista no workspace Databricks a identidade da GitHub Action do painel e dá-lhe uso do SQL Warehouse.

Uso:  python scripts/configurar_painel_sp.py --env dev --client-id <client id da aplicação findata-painel-github>
Depois: python scripts/apply_sql.py --env dev --dir sql/grants_painel --var sp=<client id>
Idempotente: se a identidade já existir, só confirma a permissão no warehouse.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from databricks.sdk import WorkspaceClient  # noqa: E402
from databricks.sdk.service.iam import ComplexValue  # noqa: E402
from databricks.sdk.service.sql import (  # noqa: E402
    WarehouseAccessControlRequest,
    WarehousePermissionLevel,
)

from src.common.config import carregar_ambiente  # noqa: E402

log = logging.getLogger("configurar_painel_sp")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="dev")
    ap.add_argument("--client-id", required=True)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    cfg = carregar_ambiente(args.env)
    w = WorkspaceClient(host=cfg["databricks"]["host"], auth_type="azure-cli")
    existentes = list(w.service_principals.list(filter=f'applicationId eq "{args.client_id}"'))
    if existentes:
        log.info("identidade já registada no workspace (id %s)", existentes[0].id)
    else:
        sp = w.service_principals.create(application_id=args.client_id, display_name="findata-painel-github",
                                         entitlements=[ComplexValue(value="databricks-sql-access")])
        log.info("identidade registada no workspace (id %s)", sp.id)

    wh = next(x for x in w.warehouses.list() if x.name == cfg["databricks"]["sql_warehouse_name"])
    w.warehouses.update_permissions(wh.id, access_control_list=[WarehouseAccessControlRequest(
        service_principal_name=args.client_id, permission_level=WarehousePermissionLevel.CAN_USE)])
    log.info("CAN_USE no warehouse %s", wh.name)


if __name__ == "__main__":
    main()
