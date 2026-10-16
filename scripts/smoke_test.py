"""Teste de fumaça depois do deploy: corre a tarefa de testes de integração do job de auditoria e espera.

Uso:  python scripts/smoke_test.py --env dev [--timeout-min 30]
Sai com código 1 se a execução não terminar com sucesso (o pipeline de CD falha).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from databricks.sdk import WorkspaceClient  # noqa: E402

from src.common.config import carregar_ambiente  # noqa: E402

log = logging.getLogger("smoke_test")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="dev")
    ap.add_argument("--timeout-min", type=int, default=30)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = carregar_ambiente(args.env)
    w = WorkspaceClient(host=cfg["databricks"]["host"], auth_type="azure-cli")
    nome = f"findata_{args.env}_auditoria"
    job = next(iter(w.jobs.list(name=nome)), None)
    if not job:
        log.error("job %s não encontrado", nome)
        return 1
    run_id = w.jobs.run_now(job.job_id, only=["testes_integracao"]).run_id
    log.info("testes de integração: %s/jobs/%s/runs/%s", cfg["databricks"]["host"], job.job_id, run_id)
    limite = time.time() + args.timeout_min * 60
    while time.time() < limite:
        r = w.jobs.get_run(run_id)
        if r.state.life_cycle_state.value in ("TERMINATED", "INTERNAL_ERROR", "SKIPPED"):
            resultado = r.state.result_state.value if r.state.result_state else r.state.life_cycle_state.value
            log.info("resultado: %s %s", resultado, r.state.state_message or "")
            return 0 if resultado == "SUCCESS" else 1
        time.sleep(20)
    log.error("tempo esgotado à espera da execução %s", run_id)
    return 1


if __name__ == "__main__":
    sys.exit(main())
