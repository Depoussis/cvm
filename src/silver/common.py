"""Passos partilhados das cargas silver: seleção de bronze pendente, quarentena e MERGE com contagens."""
from __future__ import annotations

from datetime import date


def sql_pendentes(tabela_bronze: str, catalogo: str, source_system: str, entidade: str, filtro: str,
                  reprocessar: bool) -> str:
    """Registos bronze da entidade ainda não consolidados na silver.

    Pendente = ingerido por uma execução cuja carga silver desta entidade ainda não terminou com sucesso.
    Assim, uma falha na silver não perde dados: a execução seguinte volta a apanhar essas linhas, mesmo que a
    bronze tenha marcado o payload seguinte como duplicado. Em `reprocess`, toda a bronze da entidade é relida.
    """
    base = f"SELECT * FROM {tabela_bronze} WHERE {filtro}"
    if reprocessar:
        return base
    return (f"{base} AND _pipeline_run_id NOT IN ("
            f"SELECT pipeline_run_id FROM {catalogo}.control.pipeline_execution "
            f"WHERE layer = 'silver' AND source_system = '{source_system}' AND entity_name = '{entidade}' "
            f"AND execution_status = 'SUCCEEDED')")


def caminho_quarentena(catalogo: str, fonte: str, entidade: str, hoje: date, run_id: str) -> str:
    return f"/Volumes/{catalogo}/ops/quarantine/{fonte}/{entidade}/ingestion_date={hoje.isoformat()}/{run_id}"


def quarentena(spark, df_invalidos, caminho: str, motivo: str) -> int:
    """Escreve os registos rejeitados (com o motivo) em JSON no volume de quarentena."""
    from pyspark.sql import functions as F

    n = df_invalidos.count()
    if n:
        df_invalidos.withColumn("_motivo_rejeicao", F.lit(motivo)).write.mode("append").json(caminho)
    return n


def executar_merge(spark, instrucao: str) -> tuple[int, int]:
    """Executa um MERGE Delta e devolve (inseridos, atualizados) a partir das métricas da própria instrução."""
    m = spark.sql(instrucao).first().asDict()
    return int(m.get("num_inserted_rows") or 0), int(m.get("num_updated_rows") or 0)
