# Databricks notebook source
# MAGIC %md
# MAGIC # Testes de integração (Spark + Delta + Unity Catalog)
# MAGIC Exercita, em tabelas temporárias no schema `ops`, a mesma lógica usada pelos pipelines:
# MAGIC SCD1 (contagens e CDF de reapresentações), SCD2 (alteração, ausência e reaparecimento), watermark que nunca
# MAGIC recua e registo de execuções; compara a gold da B3 (incremental por CDF) com uma reconstrução completa.
# MAGIC Remove tudo o que cria, também em caso de falha. Falha se alguma verificação falhar.

# COMMAND ----------

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd().parents[1]))

from src.common import notebook

notebook.declarar(dbutils)
p = notebook.ler(dbutils)

# COMMAND ----------

import uuid

from src.audit import control
from src.audit.reapresentacoes import sql_reapresentacoes
from src.scd.merge_sql import expr_hash, fechar_ausentes_scd2, merge_scd1, merge_scd2
from src.silver.common import executar_merge

k = p.catalogo
sufixo = uuid.uuid4().hex[:8]
T1, T2 = f"{k}.ops._teste_scd1_{sufixo}", f"{k}.ops._teste_scd2_{sufixo}"
FONTE_TESTE = f"teste_integracao_{sufixo}"
RUN = f"teste-{sufixo}"
resultados = []


def verificar(nome: str, obtido, esperado) -> None:
    ok = obtido == esperado
    resultados.append((nome, ok, obtido, esperado))
    print(f"{'OK ' if ok else 'FALHA'} {nome}: obtido={obtido!r} esperado={esperado!r}")


def origem(view: str, linhas: list[tuple], esquema: str, colunas: list[str]) -> None:
    (spark.createDataFrame(linhas, esquema).selectExpr("*", f"{expr_hash(colunas)} AS record_hash",
                                                       f"'{RUN}' AS _pipeline_run_id")
     .createOrReplaceTempView(view))

# COMMAND ----------

try:
    # ---------------------------------------------------------------- SCD1 + CDF
    spark.sql(f"""CREATE TABLE {T1} (chave INT NOT NULL, dia DATE NOT NULL, valor DECIMAL(24,8), record_hash STRING,
                  _inserted_at TIMESTAMP, _updated_at TIMESTAMP, _pipeline_run_id STRING)
                  TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')""")
    esq = "chave INT, dia STRING, valor STRING"
    origem("_s1", [(1, "2026-01-01", "1.5"), (2, "2026-01-01", "2.0")], esq, ["valor"])
    spark.sql("CREATE OR REPLACE TEMP VIEW _s1t AS SELECT chave, to_date(dia) AS dia, CAST(valor AS DECIMAL(24,8)) AS valor, "
              "record_hash, _pipeline_run_id FROM _s1")
    sql1 = merge_scd1(T1, "_s1t", ["chave", "dia"], ["valor"])
    verificar("scd1 primeira carga insere 2", executar_merge(spark, sql1), (2, 0))
    verificar("scd1 repetir não altera nada", executar_merge(spark, sql1), (0, 0))
    v_antes = spark.sql(f"DESCRIBE HISTORY {T1} LIMIT 1").first()["version"]

    origem("_s1", [(1, "2026-01-01", "1.75"), (3, "2026-01-02", "9.0")], esq, ["valor"])
    spark.sql("CREATE OR REPLACE TEMP VIEW _s1t AS SELECT chave, to_date(dia) AS dia, CAST(valor AS DECIMAL(24,8)) AS valor, "
              "record_hash, _pipeline_run_id FROM _s1")
    verificar("scd1 revisão: 1 nova, 1 alterada", executar_merge(spark, sql1), (1, 1))
    verificar("scd1 valor revisto", float(spark.sql(f"SELECT valor FROM {T1} WHERE chave = 1").first()[0]), 1.75)
    v_depois = spark.sql(f"DESCRIBE HISTORY {T1} LIMIT 1").first()["version"]
    reap = spark.sql(sql_reapresentacoes(T1, ["chave", "dia"], ["valor"], v_antes + 1, v_depois)).collect()
    verificar("cdf deteta 1 reapresentação", len(reap), 1)
    if reap:
        verificar("reapresentação: valor anterior", reap[0]["valores_anteriores"], '{"valor":1.50000000}')
        verificar("reapresentação: valor novo", reap[0]["valores_novos"], '{"valor":1.75000000}')
        verificar("reapresentação: colunas", list(reap[0]["colunas_alteradas"]), ["valor"])

    # ---------------------------------------------------------------- SCD2
    spark.sql(f"""CREATE TABLE {T2} (id STRING NOT NULL, nome STRING, record_hash STRING, valid_from TIMESTAMP,
                  valid_to TIMESTAMP, is_current BOOLEAN, _pipeline_run_id STRING)""")
    s2 = lambda linhas: origem("_s2", linhas, "id STRING, nome STRING", ["nome"])  # noqa: E731
    sql2, fecha = merge_scd2(T2, "_s2", ["id"], ["nome"]), fechar_ausentes_scd2(T2, "_s2", ["id"])
    atuais = lambda: sorted(tuple(r) for r in spark.sql(f"SELECT id, nome FROM {T2} WHERE is_current").collect())  # noqa: E731

    s2([("A", "Alfa"), ("B", "Beta")])
    verificar("scd2 carga inicial", executar_merge(spark, sql2), (2, 0))
    verificar("scd2 repetir não cria versões", executar_merge(spark, sql2), (0, 0))
    s2([("A", "Alfa SA"), ("B", "Beta")])
    verificar("scd2 alteração fecha 1 e insere 1", executar_merge(spark, sql2), (1, 1))
    verificar("scd2 versões atuais após alteração", atuais(), [("A", "Alfa SA"), ("B", "Beta")])
    verificar("scd2 histórico de A", spark.sql(f"SELECT count(*) FROM {T2} WHERE id = 'A'").first()[0], 2)
    verificar("scd2 versão fechada tem valid_to",
              spark.sql(f"SELECT count(*) FROM {T2} WHERE NOT is_current AND valid_to IS NULL").first()[0], 0)
    s2([("A", "Alfa SA")])
    executar_merge(spark, sql2)
    verificar("scd2 chave ausente do snapshot é fechada", executar_merge(spark, fecha)[1], 1)
    verificar("scd2 só A atual", atuais(), [("A", "Alfa SA")])
    s2([("A", "Alfa SA"), ("B", "Beta")])
    verificar("scd2 reaparecimento cria versão nova", executar_merge(spark, sql2), (1, 0))
    verificar("scd2 uma versão atual por chave",
              spark.sql(f"SELECT max(n) FROM (SELECT count(*) n FROM {T2} WHERE is_current GROUP BY id)").first()[0], 1)

    # ---------------------------------------------------------------- watermark e execuções (tabelas reais)
    e = control.Execucao(k, RUN, "teste_integracao", FONTE_TESTE, "entidade", "silver", "incremental")
    control.iniciar(spark, e)
    def estado():
        return spark.sql(f"SELECT execution_status FROM {k}.control.pipeline_execution "
                         f"WHERE pipeline_run_id = '{RUN}'").first()[0]
    verificar("execução registada como RUNNING", estado(), "RUNNING")
    for valor in ("2026-10-10", "2026-10-01"):
        control.confirmar_watermark(spark, e, "reference_date", valor, 30)
    verificar("watermark não recua", control.ler_watermark(spark, k, FONTE_TESTE, "entidade")["watermark_value"], "2026-10-10")
    control.confirmar_watermark(spark, e, "reference_date", "2026-10-12", None)
    wm = control.ler_watermark(spark, k, FONTE_TESTE, "entidade")
    verificar("watermark avança", wm["watermark_value"], "2026-10-12")
    verificar("review_window mantido quando não indicado", wm["review_window_days"], 30)
    control.falhar(spark, e, ValueError("erro de teste"))
    verificar("falha registada", estado(), "FAILED")
    control.concluir(spark, e, control.Contagens(read=1))
    verificar("repetir a mesma execução atualiza a linha (sem duplicar)",
              spark.sql(f"SELECT count(*) FROM {k}.control.pipeline_execution WHERE pipeline_run_id = '{RUN}'").first()[0], 1)
finally:
    for t in (T1, T2):
        spark.sql(f"DROP TABLE IF EXISTS {t}")
    spark.sql(f"DELETE FROM {k}.control.pipeline_execution WHERE pipeline_run_id = '{RUN}'")
    spark.sql(f"DELETE FROM {k}.control.ingestion_watermark WHERE source_system = '{FONTE_TESTE}'")

# COMMAND ----------

# Gold da B3 carregada de forma incremental pelo Change Data Feed: tem de coincidir com uma reconstrução completa
# (só leitura; ignorado enquanto a tabela não existir).
if spark.catalog.tableExists(f"{k}.gold.fct_cotacao_diaria"):
    from src.gold.cotacoes import sql_diferencas
    dif = spark.sql(sql_diferencas(k))
    verificar("gold B3 incremental (CDF) igual à reconstrução completa", dif.count(), 0)

# COMMAND ----------

falhas = [r for r in resultados if not r[1]]
print(f"{len(resultados) - len(falhas)}/{len(resultados)} verificações OK")
if falhas:
    raise AssertionError(f"{len(falhas)} verificações falharam: {falhas}")
