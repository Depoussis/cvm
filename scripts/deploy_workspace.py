"""Publica o código no workspace Databricks e cria/atualiza os jobs (Banco Central e CVM).

Uso:
  python scripts/deploy_workspace.py --env dev                 # sobe src/, config/, notebooks/, sql/ e atualiza o job
  python scripts/deploy_workspace.py --env dev --run backfill  # e dispara uma execução (backfill|incremental)
  python scripts/deploy_workspace.py --env dev --fonte cvm     # só o job da CVM

O código fica em /Workspace/Shared/findata_<env>/ (os notebooks importam src/ a partir dessa pasta).
Jobs novos são criados com o agendamento em PAUSE; num job existente o estado do agendamento é mantido.
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
NOME_JOB = "findata_{env}_{fonte}"
# fonte -> (descrição, cron em config databricks.job, tarefas: (chave, notebook, dependências, retries))
JOBS = {
    "bcb": ("Banco Central (SGS e PTAX): bronze -> silver -> gold. Ver docs/pipelines_bcb.md.", "cron", [
        ("bronze_sgs", "bronze/bcb_sgs", [], 2), ("bronze_ptax", "bronze/bcb_ptax", [], 2),
        ("silver_sgs", "silver/bcb_sgs", ["bronze_sgs"], 0), ("silver_ptax", "silver/bcb_ptax", ["bronze_ptax"], 0),
        ("gold_bcb", "gold/bcb", ["silver_sgs", "silver_ptax"], 0)]),
    "cvm": ("CVM (fundos e companhias abertas): bronze -> silver -> gold. Ver docs/pipelines_cvm.md.", "cron_cvm", [
        ("bronze_cvm", "bronze/cvm", [], 2), ("silver_cvm", "silver/cvm", ["bronze_cvm"], 0),
        ("gold_cvm", "gold/cvm", ["silver_cvm"], 0)]),
}


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


def definicao_job(env: str, destino: str, cfg: dict, email: str, fonte: str) -> dict:
    descricao, chave_cron, tarefas = JOBS[fonte]
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
        name=NOME_JOB.format(env=env, fonte=fonte),
        description=descricao,
        tags={"projeto": "findata", "ambiente": env, "fonte": fonte},
        max_concurrent_runs=1,
        parameters=[jobs.JobParameterDefinition(name="env", default=env),
                    jobs.JobParameterDefinition(name="run_mode", default="incremental"),
                    jobs.JobParameterDefinition(name="pipeline_run_id", default="job-{{job.run_id}}"),
                    jobs.JobParameterDefinition(name="data_inicio", default=""),
                    jobs.JobParameterDefinition(name="data_fim", default=""),
                    jobs.JobParameterDefinition(name="entidades", default="")],
        job_clusters=clusters, environments=ambientes,
        tasks=[tarefa(chave, nb_, dep, r) for chave, nb_, dep, r in tarefas],
        schedule=jobs.CronSchedule(quartz_cron_expression=job_cfg[chave_cron], timezone_id=job_cfg["timezone"],
                                   pause_status=jobs.PauseStatus.PAUSED),
        email_notifications=jobs.JobEmailNotifications(on_failure=[email]),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="dev")
    ap.add_argument("--run", choices=["backfill", "incremental"], help="dispara uma execução depois do deploy")
    ap.add_argument("--fonte", action="append", choices=sorted(JOBS), help="jobs a atualizar (por omissão: todos)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    args.fonte = args.fonte or sorted(JOBS)
    cfg = carregar_ambiente(args.env)
    w = WorkspaceClient(host=cfg["databricks"]["host"], auth_type="azure-cli")
    email = w.current_user.me().user_name
    destino = f"/Workspace/Shared/findata_{args.env}"
    log.info("%d ficheiros publicados em %s", publicar_codigo(w, destino), destino)

    for fonte in args.fonte:
        definicao = definicao_job(args.env, destino, cfg, email, fonte)
        existente = next(iter(w.jobs.list(name=definicao["name"])), None)
        if existente:
            # mantém o estado do agendamento (ativado à mão na interface) em vez de voltar a pausar
            atual = w.jobs.get(existente.job_id).settings.schedule
            if atual and atual.pause_status:
                definicao["schedule"].pause_status = atual.pause_status
            w.jobs.reset(existente.job_id, jobs.JobSettings(**definicao))
            job_id = existente.job_id
            log.info("job %s atualizado (id %s), agendamento %s", definicao["name"], job_id,
                     definicao["schedule"].pause_status.value)
        else:
            job_id = w.jobs.create(**definicao).job_id
            log.info("job %s criado (id %s), agendamento em PAUSE", definicao["name"], job_id)
        if args.run:
            run = w.jobs.run_now(job_id, job_parameters={"run_mode": args.run})
            log.info("execução %s disparada: %s/jobs/%s/runs/%s", args.run, cfg["databricks"]["host"], job_id, run.run_id)

if __name__ == "__main__":
    main()
