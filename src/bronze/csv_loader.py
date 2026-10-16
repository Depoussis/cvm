"""Carga de CSV (já guardados no volume raw) para tabelas bronze só com texto + auditoria."""
from __future__ import annotations

import re
from src.bronze.writer import Origem

AUDITORIA = [
    ("_schema_version", "STRING"), ("_source_file_name", "STRING"), ("_source_encoding", "STRING"),
    ("_reference_period", "STRING"),
    ("_corrupt_record", "STRING"),  # linha original quando o número de campos não bate com o cabeçalho
    ("_source_system", "STRING NOT NULL"), ("_source_entity", "STRING NOT NULL"), ("_source_url", "STRING NOT NULL"),
    ("_source_file_path", "STRING NOT NULL"), ("_file_hash", "STRING NOT NULL"), ("_record_hash", "STRING NOT NULL"),
    ("_request_start", "DATE"), ("_request_end", "DATE"),
    ("_ingestion_timestamp", "TIMESTAMP NOT NULL"), ("_pipeline_run_id", "STRING NOT NULL"),
]
_NOME = re.compile(r"^[a-z0-9_]+$")


def ddl_tabela(tabela: str, colunas: list[str], comentario: str, cluster_por: list[str]) -> str:
    for c in colunas:
        if not _NOME.match(c):
            raise ValueError(f"nome de coluna inesperado: {c!r}")
    corpo = ",\n  ".join([f"`{c}` STRING" for c in colunas] + [f"{n} {t}" for n, t in AUDITORIA])
    cluster = f"\nCLUSTER BY ({', '.join(cluster_por)})" if cluster_por else ""
    return (f"CREATE TABLE IF NOT EXISTS {tabela} (\n  {corpo}\n)\nUSING DELTA{cluster}\n"
            f"COMMENT '{comentario.replace(chr(39), '')}'")


def garantir_tabela(spark, tabela: str, colunas: list[str], comentario: str, cluster_por: list[str]) -> None:
    """Cria a tabela bronze; se já existir, acrescenta colunas novas do contrato (nova versão de cabeçalho)."""
    spark.sql(ddl_tabela(tabela, colunas, comentario, cluster_por))
    existentes = {f.name for f in spark.table(tabela).schema.fields}
    novas = [c for c in colunas if c not in existentes]
    if novas:
        spark.sql(f"ALTER TABLE {tabela} ADD COLUMNS ({', '.join(f'`{c}` STRING' for c in novas)})")


def carregar_csv(spark, caminho_csv: str, tabela: str, colunas_ficheiro: list[str], codificacao: str,
                 separador: str, versao: str, origem: Origem, periodo: str | None, run_id: str) -> int:
    """Lê o CSV como texto (sem inferência de tipos) e acrescenta à bronze. Devolve o número de linhas."""
    from pyspark.sql import functions as F

    df = (spark.read.option("header", True).option("sep", separador).option("encoding", codificacao)
          .option("quote", '"').option("escape", '"')
          .option("mode", "PERMISSIVE").option("columnNameOfCorruptRecord", "_corrupt_record")
          .schema(", ".join([f"`{c}` STRING" for c in colunas_ficheiro] + ["_corrupt_record STRING"]))
          .csv(caminho_csv))
    df = df.toDF(*[c.lower() for c in colunas_ficheiro], "_corrupt_record")
    negocio = [c.lower() for c in colunas_ficheiro]
    df = (df.withColumn("_record_hash", F.sha2(F.concat_ws("||", *[F.coalesce(F.col(c), F.lit("∅")) for c in negocio]), 256))
            .withColumn("_schema_version", F.lit(versao))
            .withColumn("_source_file_name", F.lit(caminho_csv.rsplit("/", 1)[-1]))
            .withColumn("_source_encoding", F.lit(codificacao))
            .withColumn("_reference_period", F.lit(periodo))
            .withColumn("_source_system", F.lit(origem.source_system))
            .withColumn("_source_entity", F.lit(origem.entity))
            .withColumn("_source_url", F.lit(origem.url))
            .withColumn("_source_file_path", F.lit(origem.stored_path))
            .withColumn("_file_hash", F.lit(origem.file_hash))
            .withColumn("_request_start", F.lit(None).cast("date"))
            .withColumn("_request_end", F.lit(None).cast("date"))
            .withColumn("_ingestion_timestamp", F.current_timestamp())
            .withColumn("_pipeline_run_id", F.lit(run_id)))
    alvo = spark.table(tabela).columns
    for c in alvo:
        if c not in df.columns:
            df = df.withColumn(c, F.lit(None).cast("string"))
    df.select(*alvo).write.mode("append").saveAsTable(tabela)
    return spark.table(tabela).where(F.col("_file_hash") == origem.file_hash).where(F.col("_pipeline_run_id") == run_id).count()

