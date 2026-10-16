"""Regras de qualidade declarativas: cada regra é uma consulta que devolve os registos inválidos.

Severidades:
- CRITICAL: bloqueia a publicação gold e o avanço do watermark.
- HIGH: regista a falha e bloqueia a publicação gold.
- INFO: só regista (ex.: reconciliações entre fontes).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from src.audit.control import agora_utc

SEVERIDADES = {"CRITICAL", "HIGH", "INFO"}


@dataclass(frozen=True)
class Regra:
    nome: str
    descricao: str
    severidade: str
    tabela: str          # tabela avaliada (nome UC), para o registo
    invalidos_sql: str   # SELECT que devolve os registos que violam a regra
    total_sql: str       # SELECT count(*) dos registos avaliados

    def __post_init__(self) -> None:
        if self.severidade not in SEVERIDADES:
            raise ValueError(f"severidade inválida: {self.severidade}")

    @property
    def bloqueia(self) -> bool:
        return self.severidade in {"CRITICAL", "HIGH"}


@dataclass
class Resultado:
    regra: Regra
    avaliados: int
    falhados: int
    amostra: list[dict]

    @property
    def passou(self) -> bool:
        return self.falhados == 0


def avaliar(spark, regras: list[Regra], amostra: int = 5) -> list[Resultado]:
    saida = []
    for r in regras:
        invalidos = spark.sql(r.invalidos_sql)
        falhados = invalidos.count()
        exemplos = [x.asDict() for x in invalidos.limit(amostra).collect()] if falhados else []
        saida.append(Resultado(r, spark.sql(r.total_sql).first()[0], falhados, exemplos))
    return saida


def gravar(spark, catalogo: str, run_id: str, resultados: list[Resultado]) -> None:
    if not resultados:
        return
    tabela = f"{catalogo}.control.data_quality_results"
    ts = agora_utc()
    linhas = [{
        "dq_result_id": uuid.uuid4().hex, "pipeline_run_id": run_id, "table_name": x.regra.tabela,
        "rule_name": x.regra.nome, "rule_description": x.regra.descricao, "severity": x.regra.severidade,
        "result": "PASSED" if x.passou else "FAILED", "records_evaluated": x.avaliados,
        "records_failed": x.falhados,
        "failed_sample": json.dumps(x.amostra, ensure_ascii=False, default=str)[:4000] if x.amostra else None,
        "blocks_publication": (not x.passou) and x.regra.bloqueia, "executed_at": ts,
    } for x in resultados]
    spark.createDataFrame(linhas, schema=spark.table(tabela).schema).write.mode("append").saveAsTable(tabela)


def falhas_bloqueantes(spark, catalogo: str, run_id: str) -> list[str]:
    linhas = spark.sql(f"""
        SELECT table_name, rule_name, records_failed FROM {catalogo}.control.data_quality_results
        WHERE pipeline_run_id = :r AND blocks_publication
    """, args={"r": run_id}).collect()
    return [f"{x.table_name}: {x.rule_name} ({x.records_failed} registos)" for x in linhas]
