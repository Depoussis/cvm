# Databricks notebook source
# MAGIC %md
# MAGIC # Silver · BCB PTAX
# MAGIC - `silver.bcb_ptax_moedas` (SCD2): versão nova quando nome ou tipo da moeda muda.
# MAGIC - `silver.bcb_ptax_cotacoes` (SCD1): uma linha por (moeda, data/hora, boletim), valores em DECIMAL(24,8).
# MAGIC   `data_hora_cotacao` guarda a hora de Brasília tal como publicada.

# COMMAND ----------

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd().parents[1]))

from src.common import notebook

notebook.declarar(dbutils)
p = notebook.ler(dbutils)
print(p)

# COMMAND ----------

from datetime import date

from pyspark.sql import functions as F
from pyspark.sql.window import Window

from src.audit import control
from src.common.config import carregar_yaml
from src.quality import rules as dq
from src.scd.merge_sql import expr_hash, merge_scd1, merge_scd2
from src.silver.common import caminho_quarentena, executar_merge, quarentena, sql_pendentes

FONTE = "bcb_ptax"
cfg = carregar_yaml("sources/bcb.yaml")["bcb_ptax"]
hoje = date.today()
REGEX_NUM = r"^-?[0-9]+([.][0-9]{1,8})?$"
BOLETINS = ("Abertura", "Intermediário", "Fechamento")
NUMERICAS = ["paridade_compra", "paridade_venda", "cotacao_compra", "cotacao_venda"]
erros = {}

# COMMAND ----------

# MAGIC %md ## Moedas (SCD2)

# COMMAND ----------

if p.escolhida("moedas"):
    e = control.Execucao(p.catalogo, p.run_id, "silver_bcb_ptax", FONTE, "moedas", "silver", p.run_mode)
    control.iniciar(spark, e)
    try:
        src = spark.sql(sql_pendentes(f"{p.catalogo}.bronze.bcb_ptax_moedas", p.catalogo, FONTE, "moedas", "true",
                                      p.run_mode == "reprocess"))
        ultimo = Window.partitionBy("simbolo").orderBy(F.col("_ingestion_timestamp").desc())
        colunas = ["nome_formatado", "tipo_moeda"]
        (src.withColumn("_rn", F.row_number().over(ultimo)).where("_rn = 1")
            .select("simbolo", *colunas)
            .withColumn("record_hash", F.expr(expr_hash(colunas)))
            .withColumn("_pipeline_run_id", F.lit(p.run_id))
            .createOrReplaceTempView("_moedas_src"))
        lidos = spark.table("_moedas_src").count()
        ins, upd = executar_merge(spark, merge_scd2(f"{p.catalogo}.silver.bcb_ptax_moedas", "_moedas_src", ["simbolo"], colunas))
        control.concluir(spark, e, control.Contagens(read=lidos, inserted=ins, updated=upd))
        print(f"moedas: lidas={lidos} novas versões={ins} versões fechadas={upd}")
    except Exception as ex:
        control.falhar(spark, e, ex)
        erros["moedas"] = repr(ex)

# COMMAND ----------

# MAGIC %md ## Cotações (SCD1)

# COMMAND ----------

bronze = f"{p.catalogo}.bronze.bcb_ptax_cotacoes"
destino = f"{p.catalogo}.silver.bcb_ptax_cotacoes"
for moeda in cfg["moedas"]:
    entidade = f"cotacao_{moeda}"
    if not p.escolhida(entidade):
        continue
    e = control.Execucao(p.catalogo, p.run_id, "silver_bcb_ptax", FONTE, entidade, "silver", p.run_mode,
                         parameters={"moeda": moeda})
    control.iniciar(spark, e)
    c = control.Contagens()
    try:
        filtro = f"moeda = '{moeda}'"
        src_sql = sql_pendentes(bronze, p.catalogo, FONTE, entidade, filtro, p.run_mode == "reprocess")
        tipado = spark.sql(src_sql).withColumn("data_hora", F.expr("try_cast(data_hora_cotacao AS TIMESTAMP)"))
        ok_numeros = " AND ".join(f"coalesce({n} rlike '{REGEX_NUM}', false)" for n in NUMERICAS)
        tipado = tipado.withColumn("_valido", F.expr(f"data_hora IS NOT NULL AND tipo_boletim IS NOT NULL AND {ok_numeros}"))
        c.read = tipado.count()
        c.rejected = quarentena(spark, tipado.where("NOT _valido").drop("_valido"),
                                caminho_quarentena(p.catalogo, FONTE, entidade, hoje, p.run_id),
                                "data/hora, boletim ou valores fora do formato da API PTAX")
        ultimo = Window.partitionBy("moeda", "data_hora", "tipo_boletim").orderBy(F.col("_ingestion_timestamp").desc())
        (tipado.where("_valido").withColumn("_rn", F.row_number().over(ultimo)).where("_rn = 1")
               .select("moeda", F.col("data_hora").alias("data_hora_cotacao"),
                       F.to_date("data_hora").alias("data_cotacao"), "tipo_boletim",
                       *[F.col(n).cast("decimal(24,8)").alias(n) for n in NUMERICAS])
               .withColumn("record_hash", F.expr(expr_hash(NUMERICAS)))
               .withColumn("_pipeline_run_id", F.lit(p.run_id))
               .createOrReplaceTempView("_ptax_src"))
        n_validos = spark.table("_ptax_src").count()
        c.inserted, c.updated = executar_merge(spark, merge_scd1(
            destino, "_ptax_src", ["moeda", "data_hora_cotacao", "tipo_boletim"], ["data_cotacao", *NUMERICAS]))
        c.unchanged = n_validos - c.inserted - c.updated

        total = f"SELECT count(*) FROM {destino} WHERE {filtro}"
        regras = [
            dq.Regra("chave_unica", "Uma linha por (moeda, data/hora, boletim)", "CRITICAL", destino,
                     f"SELECT data_hora_cotacao, tipo_boletim, count(*) n FROM {destino} WHERE {filtro} "
                     f"GROUP BY 1, 2 HAVING n > 1", total),
            dq.Regra("cotacao_positiva", "Cotações e paridades maiores que zero", "CRITICAL", destino,
                     f"SELECT * FROM {destino} WHERE {filtro} AND least({', '.join(NUMERICAS)}) <= 0", total),
            dq.Regra("venda_maior_igual_compra", "Cotação de venda não inferior à de compra", "HIGH", destino,
                     f"SELECT * FROM {destino} WHERE {filtro} AND cotacao_venda < cotacao_compra", total),
            dq.Regra("boletim_conhecido", f"tipo_boletim em {BOLETINS}", "HIGH", destino,
                     f"SELECT * FROM {destino} WHERE {filtro} AND tipo_boletim NOT IN {BOLETINS}", total),
            # O BCB às vezes publica o fechamento duas vezes, com milissegundos de diferença e os mesmos valores
            # (ex.: 23/04/2025). Repetição idêntica é só registada; valores diferentes no mesmo dia bloqueiam.
            dq.Regra("fechamento_unico_por_dia", "Um único valor de fechamento por dia", "HIGH", destino,
                     f"SELECT data_cotacao, count(DISTINCT record_hash) n FROM {destino} WHERE {filtro} "
                     f"AND tipo_boletim = 'Fechamento' GROUP BY 1 HAVING n > 1", total),
            dq.Regra("fechamento_repetido", "Fechamento publicado mais de uma vez com os mesmos valores", "INFO", destino,
                     f"SELECT data_cotacao, count(*) n FROM {destino} WHERE {filtro} AND tipo_boletim = 'Fechamento' "
                     f"GROUP BY 1 HAVING n > 1 AND count(DISTINCT record_hash) = 1", total),
            dq.Regra("formato_api", "Campos da API convertíveis sem perda", "HIGH", bronze,
                     f"SELECT * FROM ({src_sql}) x WHERE try_cast(data_hora_cotacao AS TIMESTAMP) IS NULL "
                     f"OR tipo_boletim IS NULL OR NOT ({ok_numeros})", f"SELECT count(*) FROM ({src_sql}) x"),
        ]
        resultados = dq.avaliar(spark, regras)
        dq.gravar(spark, p.catalogo, p.run_id, resultados)
        criticas = [r.regra.nome for r in resultados if not r.passou and r.regra.severidade == "CRITICAL"]
        falhas = [r.regra.nome for r in resultados if not r.passou]

        maximo = spark.sql(f"SELECT max(data_cotacao) FROM {destino} WHERE {filtro}").first()[0]
        if maximo and not criticas:
            control.confirmar_watermark(spark, e, "reference_date", maximo.isoformat(), cfg["revisao_dias"])
        control.concluir(spark, e, c)
        print(f"{entidade}: lidos={c.read} novos={c.inserted} alterados={c.updated} iguais={c.unchanged} "
              f"rejeitados={c.rejected} watermark={maximo} falhas={falhas}")
        if criticas:
            raise RuntimeError(f"regras críticas falharam em {entidade}: {criticas}")
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        erros[entidade] = repr(ex)

if erros:
    raise RuntimeError(f"falharam {len(erros)} entidades: {erros}")
