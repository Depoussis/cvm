"""Parâmetros comuns dos notebooks (widgets), iguais quando corridos à mão, pelo Databricks Jobs ou pelo ADF."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.bronze.writer import novo_run_id
from src.common.config import carregar_ambiente


@dataclass
class Parametros:
    env: str
    catalogo: str
    run_mode: str
    run_id: str
    data_inicio: date | None
    data_fim: date | None
    entidades: set[str]          # vazio = todas

    def escolhida(self, entidade: str) -> bool:
        return not self.entidades or entidade in self.entidades


def declarar(dbutils) -> None:
    dbutils.widgets.dropdown("env", "dev", ["dev", "test", "prod"])
    dbutils.widgets.dropdown("run_mode", "incremental", ["incremental", "backfill", "reprocess", "reconciliation"])
    dbutils.widgets.text("pipeline_run_id", "", "pipeline_run_id (vazio = gerado)")
    dbutils.widgets.text("data_inicio", "", "data_inicio AAAA-MM-DD")
    dbutils.widgets.text("data_fim", "", "data_fim AAAA-MM-DD")
    dbutils.widgets.text("entidades", "", "entidades (separadas por vírgula; vazio = todas)")


def ler(dbutils) -> Parametros:
    g = dbutils.widgets.get
    env = g("env")
    cfg = carregar_ambiente(env)
    return Parametros(
        env=env, catalogo=cfg["unity_catalog"]["catalog"], run_mode=g("run_mode"),
        run_id=g("pipeline_run_id").strip() or novo_run_id(),
        data_inicio=date.fromisoformat(g("data_inicio")) if g("data_inicio").strip() else None,
        data_fim=date.fromisoformat(g("data_fim")) if g("data_fim").strip() else None,
        entidades={e.strip() for e in g("entidades").split(",") if e.strip()},
    )
