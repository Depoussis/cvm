"""Escrita na bronze (append) e no registo de ficheiros, com as colunas de auditoria comuns."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from src.audit.control import agora_utc


def hash_registo(registo: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(registo, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


@dataclass
class Origem:
    """Metadados de um payload recebido."""
    source_system: str
    entity: str
    url: str
    stored_path: str
    file_hash: str
    size: int
    request_start: date | None
    request_end: date | None
    etag: str | None = None
    last_modified: str | None = None


def linhas_bronze(registos: list[dict[str, Any]], origem: Origem, run_id: str,
                  agora: datetime | None = None) -> list[dict[str, Any]]:
    """Acrescenta as colunas de auditoria a cada registo (os campos de negócio já vêm renomeados)."""
    ts = agora or agora_utc()
    return [{**r, "_source_system": origem.source_system, "_source_entity": origem.entity,
             "_source_url": origem.url, "_source_file_path": origem.stored_path, "_file_hash": origem.file_hash,
             "_record_hash": hash_registo(r), "_request_start": origem.request_start,
             "_request_end": origem.request_end, "_ingestion_timestamp": ts, "_pipeline_run_id": run_id}
            for r in registos]


def append(spark, tabela: str, linhas: list[dict[str, Any]]) -> int:
    if not linhas:
        return 0
    spark.createDataFrame(linhas, schema=spark.table(tabela).schema).write.mode("append").saveAsTable(tabela)
    return len(linhas)


# ---------------------------------------------------------------- registo de ficheiros

def hashes_processados(spark, catalogo: str, source_system: str, entity: str) -> set[str]:
    linhas = spark.sql(f"""
        SELECT DISTINCT file_hash_sha256 FROM {catalogo}.control.source_file_registry
        WHERE source_system = :s AND entity_name = :e AND processing_status = 'PROCESSED'
    """, args={"s": source_system, "e": entity}).collect()
    return {r[0] for r in linhas}


def linha_registo(origem: Origem, run_id: str, status: str, detalhe: str | None, periodo: str | None) -> dict[str, Any]:
    ts = agora_utc()
    return {
        "file_id": hashlib.sha256(f"{origem.file_hash}|{origem.stored_path}".encode()).hexdigest(),
        "source_system": origem.source_system, "entity_name": origem.entity, "source_url": origem.url,
        "source_file_name": origem.stored_path.rsplit("/", 1)[-1], "stored_path": origem.stored_path,
        "file_hash_sha256": origem.file_hash, "file_size_bytes": origem.size,
        "source_last_modified": None, "source_etag": origem.etag, "reference_period": periodo,
        "received_at": ts, "pipeline_run_id": run_id, "processing_status": status, "status_detail": detalhe,
        "version_number": 1, "updated_at": ts,
    }


def registar_ficheiros(spark, catalogo: str, linhas: list[dict[str, Any]]) -> None:
    """MERGE por file_id. version_number = 1 + versões anteriores (hash diferente) do mesmo source_url."""
    if not linhas:
        return
    tabela = f"{catalogo}.control.source_file_registry"
    vista = f"_registo_{uuid.uuid4().hex[:8]}"
    spark.createDataFrame(linhas, schema=spark.table(tabela).schema).createOrReplaceTempView(vista)
    spark.sql(f"""
        MERGE INTO {tabela} t
        USING (
          SELECT s.* EXCEPT (version_number),
                 CAST(1 + (SELECT count(DISTINCT x.file_hash_sha256) FROM {tabela} x
                           WHERE x.source_url = s.source_url AND x.file_hash_sha256 <> s.file_hash_sha256) AS INT)
                   AS version_number
          FROM {vista} s
        ) s ON t.file_id = s.file_id
        WHEN MATCHED THEN UPDATE SET t.processing_status = s.processing_status, t.status_detail = s.status_detail,
                                     t.pipeline_run_id = s.pipeline_run_id, t.updated_at = s.updated_at
        WHEN NOT MATCHED THEN INSERT *
    """)
    spark.catalog.dropTempView(vista)


def novo_run_id() -> str:
    return f"manual-{datetime.utcnow():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
