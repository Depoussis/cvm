# Databricks notebook source
# MAGIC %md
# MAGIC # Auditoria · Reapresentações
# MAGIC Lê o Change Data Feed das tabelas silver SCD1 desde a última versão processada e grava em
# MAGIC `control.reapresentacoes` cada valor alterado depois de publicado (antes → depois, colunas alteradas, versão
# MAGIC Delta e execução responsável). Corre no fim dos jobs BCB e CVM; é idempotente (MERGE por tabela/chave/versão).
# MAGIC Parâmetro `entidades`: nomes das tabelas (ex.: `silver.bcb_sgs_valores`); vazio = todas.

# COMMAND ----------

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd().parents[1]))

from src.common import notebook

notebook.declarar(dbutils)
# fonte = bcb | cvm (parâmetro da tarefa em cada job, para os jobs paralelos não escreverem nas mesmas linhas)
dbutils.widgets.text("fonte", "", "fonte (bcb, cvm; vazio = todas)")
p = notebook.ler(dbutils)
fonte = dbutils.widgets.get("fonte").strip()
print(p)

# COMMAND ----------

from src.audit import control
from src.audit.reapresentacoes import TABELAS_SCD1, sql_reapresentacoes, versao_texto
from src.silver.common import executar_merge

k = p.catalogo
destino = f"{k}.control.reapresentacoes"
erros = {}

for relativa, (chaves, colunas) in TABELAS_SCD1.items():
    if not p.escolhida(relativa) or (fonte and not relativa.startswith(f"silver.{fonte}_")):
        continue
    tabela = f"{k}.{relativa}"
    entidade = f"reapresentacoes:{relativa}"
    e = control.Execucao(k, p.run_id, "auditoria_reapresentacoes", "auditoria", entidade, "silver", p.run_mode)
    control.iniciar(spark, e)
    c = control.Contagens()
    try:
        ultima = spark.sql(f"DESCRIBE HISTORY {tabela} LIMIT 1").first()["version"]
        wm = control.ler_watermark(spark, k, "auditoria", entidade)
        desde = int(wm["watermark_value"]) + 1 if wm else 0
        e.watermark_start, e.watermark_end = versao_texto(desde), versao_texto(ultima)
        if desde > ultima:
            control.concluir(spark, e, c, control.STATUS_SKIPPED)
            print(f"{relativa}: sem versões novas (última {ultima})")
            continue
        spark.sql(sql_reapresentacoes(tabela, chaves, colunas, desde, ultima)).createOrReplaceTempView("_reap")
        c.read = spark.table("_reap").count()
        c.inserted, _ = executar_merge(spark, f"""
            MERGE INTO {destino} t USING _reap s
              ON t.table_name = s.table_name AND t.chave = s.chave AND t.commit_version = s.commit_version
            WHEN NOT MATCHED THEN INSERT *""")
        control.confirmar_watermark(spark, e, "delta_version", versao_texto(ultima), None)
        control.concluir(spark, e, c)
        print(f"{relativa}: versões {desde}..{ultima}, reapresentações novas={c.inserted}")
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        erros[relativa] = repr(ex)

if erros:
    raise RuntimeError(f"falharam {len(erros)} tabelas: {erros}")

# COMMAND ----------

display(spark.sql(f"""
  SELECT table_name, date(commit_timestamp) AS dia, pipeline_run_id, count(*) AS alteracoes,
         array_distinct(flatten(collect_list(colunas_alteradas))) AS colunas
  FROM {destino} GROUP BY ALL ORDER BY dia DESC, table_name"""))
