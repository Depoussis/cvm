"""Registo de execuções, watermarks e ficheiros nas tabelas de controlo (Delta).

Regras de segurança:
- A execução é registada como RUNNING no início, para que falhas a meio fiquem visíveis.
- O watermark só avança com `confirmar_watermark`, chamado depois do processamento e das regras críticas.
- Todas as escritas são MERGE por chave lógica, por isso repetir a mesma chamada não duplica linhas.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

STATUS_RUNNING, STATUS_SUCCEEDED, STATUS_FAILED, STATUS_SKIPPED = "RUNNING", "SUCCEEDED", "FAILED", "SKIPPED"
MODOS = {"backfill", "incremental", "reprocess", "reconciliation"}


def agora_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # Delta TIMESTAMP guardado em UTC


@dataclass
class Contagens:
    read: int = 0
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    rejected: int = 0
    unchanged: int = 0


@dataclass
class Execucao:
    """Contexto de uma execução de pipeline para uma entidade e camada."""
    catalogo: str
    pipeline_run_id: str
    pipeline_name: str
    source_system: str
    entity_name: str
    layer: str
    run_mode: str
    watermark_start: str | None = None
    watermark_end: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    start_timestamp: datetime = field(default_factory=agora_utc)

    def __post_init__(self) -> None:
        if self.run_mode not in MODOS:
            raise ValueError(f"run_mode inválido: {self.run_mode!r} (esperado um de {sorted(MODOS)})")
        if self.layer not in {"bronze", "silver", "gold"}:
            raise ValueError(f"layer inválida: {self.layer!r}")

    @property
    def tabela(self) -> str:
        return f"{self.catalogo}.control.pipeline_execution"


def _linha_execucao(e: Execucao, status: str, c: Contagens | None, erro: tuple[str, str] | None) -> dict[str, Any]:
    fim = None if status == STATUS_RUNNING else agora_utc()
    return {
        "pipeline_run_id": e.pipeline_run_id, "pipeline_name": e.pipeline_name, "source_system": e.source_system,
        "entity_name": e.entity_name, "layer": e.layer, "run_mode": e.run_mode,
        "start_timestamp": e.start_timestamp, "end_timestamp": fim, "execution_status": status,
        "records_read": c.read if c else None, "records_inserted": c.inserted if c else None,
        "records_updated": c.updated if c else None, "records_deleted": c.deleted if c else None,
        "records_rejected": c.rejected if c else None, "records_unchanged": c.unchanged if c else None,
        "error_code": erro[0] if erro else None, "error_message": (erro[1][:4000] if erro else None),
        "retry_count": e.retry_count, "watermark_start": e.watermark_start, "watermark_end": e.watermark_end,
        "parameters": json.dumps(e.parameters, ensure_ascii=False, sort_keys=True, default=str),
        "updated_at": agora_utc(),
    }


def _merge_execucao(spark, e: Execucao, linha: dict[str, Any]) -> None:
    df = spark.createDataFrame([linha], schema=spark.table(e.tabela).schema)
    df.createOrReplaceTempView("_exec_src")
    spark.sql(f"""
        MERGE INTO {e.tabela} t USING _exec_src s
          ON t.pipeline_run_id = s.pipeline_run_id AND t.entity_name = s.entity_name AND t.layer = s.layer
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)


def iniciar(spark, e: Execucao) -> None:
    _merge_execucao(spark, e, _linha_execucao(e, STATUS_RUNNING, None, None))
    log.info("execução iniciada", extra={"run": e.pipeline_run_id, "entity": e.entity_name, "layer": e.layer})


def concluir(spark, e: Execucao, contagens: Contagens, status: str = STATUS_SUCCEEDED) -> None:
    _merge_execucao(spark, e, _linha_execucao(e, status, contagens, None))


def falhar(spark, e: Execucao, erro: BaseException, contagens: Contagens | None = None) -> None:
    _merge_execucao(spark, e, _linha_execucao(e, STATUS_FAILED, contagens, (type(erro).__name__, str(erro))))


def ler_watermark(spark, catalogo: str, source_system: str, entity_name: str) -> dict[str, Any] | None:
    linhas = (spark.table(f"{catalogo}.control.ingestion_watermark")
              .where(f"source_system = '{source_system}' AND entity_name = '{entity_name}'")
              .limit(1).collect())
    return linhas[0].asDict() if linhas else None


def confirmar_watermark(spark, e: Execucao, watermark_type: str, watermark_value: str,
                        review_window_days: int | None = None, reconciliacao_completa: bool = False) -> None:
    """Avança o watermark. Nunca recua: se o valor novo for menor (ex.: reprocessamento antigo), mantém o atual."""
    tabela = f"{e.catalogo}.control.ingestion_watermark"
    linha = {
        "source_system": e.source_system, "entity_name": e.entity_name, "watermark_type": watermark_type,
        "watermark_value": watermark_value, "review_window_days": review_window_days,
        "last_full_reconciliation": agora_utc() if reconciliacao_completa else None,
        "pipeline_run_id": e.pipeline_run_id, "updated_at": agora_utc(),
    }
    spark.createDataFrame([linha], schema=spark.table(tabela).schema).createOrReplaceTempView("_wm_src")
    spark.sql(f"""
        MERGE INTO {tabela} t USING _wm_src s
          ON t.source_system = s.source_system AND t.entity_name = s.entity_name
        WHEN MATCHED AND s.watermark_value >= t.watermark_value THEN UPDATE SET
          watermark_type = s.watermark_type, watermark_value = s.watermark_value,
          review_window_days = coalesce(s.review_window_days, t.review_window_days),
          last_full_reconciliation = coalesce(s.last_full_reconciliation, t.last_full_reconciliation),
          pipeline_run_id = s.pipeline_run_id, updated_at = s.updated_at
        WHEN MATCHED AND s.last_full_reconciliation IS NOT NULL THEN UPDATE SET
          last_full_reconciliation = s.last_full_reconciliation, updated_at = s.updated_at
        WHEN NOT MATCHED THEN INSERT *
    """)
