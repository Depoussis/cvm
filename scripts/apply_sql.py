"""Aplica os ficheiros .sql de uma pasta no SQL Warehouse do ambiente (Statement Execution API).

Uso:  python scripts/apply_sql.py --env dev --dir sql/control [--dir sql/schemas ...]
O warehouse liga sozinho e desliga após o auto-stop configurado (1 min em dev).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from databricks.sdk import WorkspaceClient  # noqa: E402
from databricks.sdk.service.sql import StatementState  # noqa: E402

from src.common.config import carregar_ambiente  # noqa: E402
from src.common.sql_files import carregar_ficheiros  # noqa: E402

log = logging.getLogger("apply_sql")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="dev")
    ap.add_argument("--dir", required=True, action="append", help="pasta com ficheiros .sql (repetível, aplicadas por ordem)")
    ap.add_argument("--var", action="append", default=[], help="variável extra nome=valor (ex.: sp=<id da aplicação>)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    cfg = carregar_ambiente(args.env)
    w = WorkspaceClient(host=cfg["databricks"]["host"], auth_type="azure-cli")
    wh = next(x for x in w.warehouses.list() if x.name == cfg["databricks"]["sql_warehouse_name"])
    variaveis = {"catalog": cfg["unity_catalog"]["catalog"], **dict(v.split("=", 1) for v in args.var)}
    instrucoes = [i for d in args.dir for i in carregar_ficheiros(RAIZ / d, variaveis)]

    def executar(sql: str, ficheiro: str = "") -> list:
        r = w.statement_execution.execute_statement(statement=sql, warehouse_id=wh.id, wait_timeout="50s")
        while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            r = w.statement_execution.get_statement(r.statement_id)
        if r.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(f"{ficheiro}: {r.status.state} {r.status.error.message if r.status.error else ''}\n{sql[:300]}")
        return (r.result.data_array or []) if r.result else []

    for ficheiro, sql in instrucoes:
        executar(sql, ficheiro)
        log.info("%s: ok  %s", ficheiro, " ".join(sql.split())[:90])
    log.info("%d instruções aplicadas", len(instrucoes))
    devolver_vistas(executar, variaveis["catalog"])


def devolver_vistas(executar, catalogo: str) -> None:
    """CREATE OR REPLACE VIEW torna dono quem corre o script. No CD é a identidade de deploy, e o dono do catálogo
    (que corre os jobs) deixava de ler as vistas (17/10/2026). As vistas voltam sempre para o dono do catálogo."""
    dono = executar(f"SELECT catalog_owner FROM system.information_schema.catalogs WHERE catalog_name = '{catalogo}'")[0][0]
    vistas = executar(f"SELECT table_schema, table_name FROM {catalogo}.information_schema.tables "
                      f"WHERE table_type = 'VIEW' AND table_schema <> 'information_schema' AND table_owner <> '{dono}'")
    for esquema, vista in vistas:
        executar(f"ALTER VIEW {catalogo}.{esquema}.{vista} OWNER TO `{dono}`")
    if vistas:
        log.info("%d vistas devolvidas ao dono do catálogo (%s)", len(vistas), dono)


if __name__ == "__main__":
    main()
