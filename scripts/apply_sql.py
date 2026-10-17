"""Aplica os ficheiros .sql de uma pasta no SQL Warehouse do ambiente (Statement Execution API).

CREATE OR REPLACE VIEW torna dono quem corre o script (no CD, a identidade de deploy). Por isso o dono do catálogo,
que corre os jobs, tem SELECT no catálogo inteiro (docs/cicd.md); sem isso, os jobs deixam de ler as vistas.

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


if __name__ == "__main__":
    main()
