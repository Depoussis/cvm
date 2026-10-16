"""Publica o código no workspace Databricks e cria/atualiza o job do Banco Central.

Uso:
  python scripts/deploy_workspace.py --env dev                 # sobe src/, config/, notebooks/, sql/ e atualiza o job
  python scripts/deploy_workspace.py --env dev --run backfill  # e dispara uma execução (backfill|incremental)

O código fica em /Workspace/Shared/findata_<env>/ (os notebooks importam src/ a partir dessa pasta).
O job é criado com o agendamento em PAUSE; ativar só depois de validar uma execução completa.
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from databricks.sdk import WorkspaceClient  # noqa: E402
from databricks.sdk.service import jobs  # noqa: E402
from databricks.sdk.service.workspace import ImportFormat, Language  # noqa: E402

from src.common.config import carregar_ambiente  # noqa: E402

log = logging.getLogger("deploy_workspace")
PASTAS = ["src", "config", "notebooks", "sql"]
NOME_JOB = "findata_{env}_bcb"


def publicar_codigo(w: WorkspaceClient, destino: str) -> int:
    n = 0
    for pasta in PASTAS:
        for f in sorted((RAIZ / pasta).rglob("*")):
            if f.is_dir() or "__pycache__" in f.parts or f.name == ".gitkeep":
                continue
            rel = f.relative_to(RAIZ).as_posix()
            alvo = f"{destino}/{rel}"
            conteudo = f.read_bytes()
            w.workspace.mkdirs(alvo.rsplit("/", 1)[0])
            if pasta == "notebooks" and conteudo.startswith(b"# Databricks notebook source"):
                w.workspace.upload(alvo.removesuffix(".py"), io.BytesIO(conteudo), format=ImportFormat.SOURCE,
                                   language=Language.PYTHON, overwrite=True)
            else:
                w.workspace.upload(alvo, io.BytesIO(conteudo), format=ImportFormat.AUTO, overwrite=True)
            n += 1
    return n


def definicao_job(env: str, destino: str, cfg: dict, email: str) -> dict:
    job_cfg = cfg["databricks"]["job"]
    nb = lambda caminho: jobs.NotebookTask(notebook_path=f"{destino}/notebooks/{caminho}",  # noqa: E731
                                           source=jobs.Source.WORKSPACE)
    comum = dict(timeout_seconds=job_cfg["timeout_tarefa_s"])
    if job_cfg["compute"] == "serverless":
        # Tarefas de notebook em serverless: sem cluster nem environment_key (usam o ambiente do notebook).
        clusters, ambientes, computo = [], [], {}
    else:
        from databricks.sdk.service.compute import ClusterSpec, DataSecurityMode, AzureAttributes, AzureAvailability
        clusters = [jobs.JobCluster(job_cluster_key="single_node", new_cluster=ClusterSpec(
            spark_version=job_cfg["spark_version"], node_type_id=job_cfg["node_type"], num_workers=0,
            data_security_mode=DataSecurityMode.SINGLE_USER, single_user_name=email,
            spark_conf={"spark.databricks.cluster.profile": "singleNode", "spark.master": "local[*, 4]"},
            custom_tags={"ResourceClass": "SingleNode", "projeto": "findata", "ambiente": env},
            azure_attributes=AzureAttributes(availability=AzureAvailability.ON_DEMAND_AZURE)))]
        ambientes, computo = [], {"job_cluster_key": "single_node"}
    tarefa = lambda chave, caminho, depende=(), retries=0: jobs.Task(  # noqa: E731
        task_key=chave, notebook_task=nb(caminho), depends_on=[jobs.TaskDependency(task_key=d) for d in depende],
        max_retries=retries, min_retry_interval_millis=300_000, **computo, **comum)
    return dict(
        name=NOME_JOB.format(env=env),
        description="Banco Central (SGS e PTAX): bronze -> silver -> gold. Ver docs/pipelines_bcb.md.",
        tags={"projeto": "findata", "ambiente": env, "fonte": "bcb"},
        max_concurrent_runs=1,
        parameters=[jobs.JobParameterDefinition(name="env", default=env),
                    jobs.JobParameterDefinition(name="run_mode", default="incremental"),
                    jobs.JobParameterDefinition(name="pipeline_run_id", default="job-{{job.run_id}}"),
                    jobs.JobParameterDefinition(name="data_inicio", default=""),
                    jobs.JobParameterDefinition(name="data_fim", default=""),
                    jobs.JobParameterDefinition(name="entidades", default="")],
        job_clusters=clusters, environments=ambientes,
        tasks=[tarefa("bronze_sgs", "bronze/bcb_sgs", retries=2),
               tarefa("bronze_ptax", "bronze/bcb_ptax", retries=2),
               tarefa("silver_sgs", "silver/bcb_sgs", ["bronze_sgs"]),
               tarefa("silver_ptax", "silver/bcb_ptax", ["bronze_ptax"]),
               tarefa("gold_bcb", "gold/bcb", ["silver_sgs", "silver_ptax"])],
        schedule=jobs.CronSchedule(quartz_cron_expression=job_cfg["cron"], timezone_id=job_cfg["timezone"],
                                   pause_status=jobs.PauseStatus.PAUSED),
        email_notifications=jobs.JobEmailNotifications(on_failure=[email]),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="dev")
    ap.add_argument("--run", choices=["backfill", "incremental"], help="dispara uma execução depois do deploy")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    cfg = carregar_ambiente(args.env)
    w = WorkspaceClient(host=cfg["databricks"]["host"], auth_type="azure-cli")
    email = w.current_user.me().user_name
    destino = f"/Workspace/Shared/findata_{args.env}"
    log.info("%d ficheiros publicados em %s", publicar_codigo(w, destino), destino)

    definicao = definicao_job(args.env, destino, cfg, email)
    existente = next(iter(w.jobs.list(name=definicao["name"])), None)
    if existente:
        w.jobs.reset(existente.job_id, jobs.JobSettings(**definicao))
        job_id = existente.job_id
        log.info("job %s atualizado (id %s)", definicao["name"], job_id)
    else:
        job_id = w.jobs.create(**definicao).job_id
        log.info("job %s criado (id %s), agendamento em PAUSE", definicao["name"], job_id)

    if args.run:
        run = w.jobs.run_now(job_id, job_parameters={"run_mode": args.run})
        log.info("execução %s disparada: %s/jobs/%s/runs/%s", args.run, cfg["databricks"]["host"], job_id, run.run_id)


if __name__ == "__main__":
    main()
