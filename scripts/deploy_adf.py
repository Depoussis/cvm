"""Publica linked services, pipelines e gatilhos do ADF a partir de pipelines/azure_data_factory/ (ARM REST).

Uso:  python scripts/deploy_adf.py --env dev [--run pl_findata_diario]

Os JSON usam ${variavel}: env, databricks_host, databricks_workspace_id e job_id_<fonte> (IDs dos jobs Databricks
procurados pelo nome findata_<env>_<fonte>). Gatilhos novos ficam PARADOS e os já iniciados não são alterados.
Iniciar no ADF Studio
(Gerir → Gatilhos → Iniciar) ou com `az rest --method post --url .../triggers/<nome>/start?api-version=2018-06-01`.
Exige Azure CLI com login; em Git Bash no Windows, MSYS_NO_PATHCONV=1.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from databricks.sdk import WorkspaceClient  # noqa: E402

from src.common.config import carregar_ambiente  # noqa: E402

log = logging.getLogger("deploy_adf")
PASTA = RAIZ / "pipelines" / "azure_data_factory"
ORDEM = ["linkedService", "pipeline", "trigger"]
COLECAO = {"linkedService": "linkedservices", "pipeline": "pipelines", "trigger": "triggers"}
API = "api-version=2018-06-01"
_VAR = re.compile(r"\$\{(\w+)\}")


def az(*args: str) -> str:
    """Chama o Azure CLI (az, ou o módulo Python quando o executável não existe no PATH)."""
    base = [os.environ.get("AZ_CLI", "az")]
    if os.environ.get("AZ_CLI_PYTHON"):
        base = [os.environ["AZ_CLI_PYTHON"], "-m", "azure.cli"]
    r = subprocess.run(base + list(args), capture_output=True, text=True, env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    if r.returncode:
        raise RuntimeError(f"az {' '.join(args[:3])}: {r.stderr.strip()[-1500:]}")
    return r.stdout


def renderizar(texto: str, variaveis: dict[str, str]) -> str:
    em_falta = sorted({m.group(1) for m in _VAR.finditer(texto)} - variaveis.keys())
    if em_falta:
        raise KeyError(f"variáveis sem valor: {em_falta}")
    return _VAR.sub(lambda m: variaveis[m.group(1)], texto)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="dev")
    ap.add_argument("--run", help="dispara este pipeline depois do deploy (execução única, não inicia gatilhos)")
    ap.add_argument("--so", nargs="*", help="publica só estes nomes (ex.: ls_databricks_findata pl_databricks_job)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    cfg = carregar_ambiente(args.env)
    az_cfg = cfg["azure"]
    fabrica = (f"/subscriptions/{az_cfg['subscription_id']}/resourceGroups/{az_cfg['resource_group']}"
               f"/providers/Microsoft.DataFactory/factories/{az_cfg['data_factory']}")
    w = WorkspaceClient(host=cfg["databricks"]["host"], auth_type="azure-cli")
    variaveis = {
        "env": args.env,
        "databricks_host": cfg["databricks"]["host"],
        "databricks_workspace_id": (f"/subscriptions/{az_cfg['subscription_id']}/resourceGroups/"
                                    f"{az_cfg['resource_group']}/providers/Microsoft.Databricks/workspaces/"
                                    f"dbw-findata-{args.env}"),
    }
    for j in w.jobs.list(name=None):
        nome = j.settings.name if j.settings else ""
        if nome.startswith(f"findata_{args.env}_"):
            variaveis[f"job_id_{nome.removeprefix(f'findata_{args.env}_')}"] = str(j.job_id)
    log.info("jobs Databricks: %s", {k: v for k, v in variaveis.items() if k.startswith("job_id_")})

    for tipo in ORDEM:
        for f in sorted((PASTA / tipo).glob("*.json")):
            definicao = json.loads(renderizar(f.read_text(encoding="utf-8"), variaveis))
            nome = definicao["name"]
            if args.so and nome not in args.so:
                continue
            if tipo == "trigger":
                definicao["properties"].pop("runtimeState", None)
                if _estado_gatilho(fabrica, nome) == "Started":
                    # Atualizar exige parar o gatilho; não o fazemos sem pedido explícito para não desligar o
                    # agendamento em silêncio.
                    log.warning("gatilho %s está iniciado: não foi alterado (pare-o no ADF para o atualizar)", nome)
                    continue
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
                json.dump({"properties": definicao["properties"]}, tmp, ensure_ascii=False)
            try:
                az("rest", "--method", "put", "--url",
                   f"https://management.azure.com{fabrica}/{COLECAO[tipo]}/{nome}?{API}", "--body", f"@{tmp.name}")
            finally:
                os.unlink(tmp.name)
            log.info("%s %s publicado", tipo, nome)

    if args.run:
        saida = json.loads(az("rest", "--method", "post", "--url",
                              f"https://management.azure.com{fabrica}/pipelines/{args.run}/createRun?{API}"))
        log.info("execução de %s: runId %s", args.run, saida["runId"])


def _estado_gatilho(fabrica: str, nome: str) -> str | None:
    try:
        saida = az("rest", "--method", "get", "--url", f"https://management.azure.com{fabrica}/triggers/{nome}?{API}")
    except RuntimeError:
        return None  # ainda não existe
    return json.loads(saida).get("properties", {}).get("runtimeState")

if __name__ == "__main__":
    main()
