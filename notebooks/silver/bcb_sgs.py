# Databricks notebook source
# MAGIC %md
# MAGIC # Silver · BCB SGS
# MAGIC - `silver.bcb_sgs_series` (SCD2): cadastro das séries a partir de `config/series/bcb_sgs.yaml`.
# MAGIC - `silver.bcb_sgs_valores` (SCD1): converte a bronze pendente (data `dd/MM/aaaa`, valor decimal), rejeita para
# MAGIC   quarentena o que não converte, deduplica por (série, data) e faz MERGE só quando o valor muda.
# MAGIC - Regras de qualidade gravadas em `control.data_quality_results`; o watermark só avança sem rejeições
# MAGIC   nem falhas críticas.

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
from src.ingestion.bcb_sgs.client import Serie
from src.quality import rules as dq
from src.scd.merge_sql import expr_hash, merge_scd1, merge_scd2
from src.silver.common import caminho_quarentena, executar_merge, quarentena, sql_pendentes

FONTE = "bcb_sgs"
config_series = carregar_yaml("series/bcb_sgs.yaml")["series"]
series = [Serie.de_config(s) for s in config_series]
series = [s for s in series if p.escolhida(s.entidade)]
bronze = f"{p.catalogo}.bronze.bcb_sgs_valores"
destino = f"{p.catalogo}.silver.bcb_sgs_valores"
hoje = date.today()
REGEX_VALOR = r"^-?[0-9]+([.][0-9]{1,8})?$"  # cabe em DECIMAL(24,8) sem arredondar

# COMMAND ----------

# MAGIC %md ## Cadastro das séries (SCD2)

# COMMAND ----------

e = control.Execucao(p.catalogo, p.run_id, "silver_bcb_sgs", FONTE, "series", "silver", p.run_mode)
control.iniciar(spark, e)
try:
    colunas = ["nome", "responsavel", "periodicidade", "dataset_bcb"]
    (spark.createDataFrame([{"serie_codigo": int(s["codigo"]), **{k: s.get(k) for k in colunas}} for s in config_series],
                           "serie_codigo INT, nome STRING, responsavel STRING, periodicidade STRING, dataset_bcb STRING")
     .withColumn("record_hash", F.expr(expr_hash(colunas)))
     .withColumn("_pipeline_run_id", F.lit(p.run_id))
     .createOrReplaceTempView("_series_src"))
    ins, upd = executar_merge(spark, merge_scd2(f"{p.catalogo}.silver.bcb_sgs_series", "_series_src", ["serie_codigo"], colunas))
    control.concluir(spark, e, control.Contagens(read=len(config_series), inserted=ins, updated=upd))
    print(f"series: novas versões={ins} versões fechadas={upd}")
except Exception as ex:
    control.falhar(spark, e, ex)
    raise

# COMMAND ----------

# MAGIC %md ## Valores (SCD1)

# COMMAND ----------

erros = {}
for serie in series:
    e = control.Execucao(p.catalogo, p.run_id, "silver_bcb_sgs", FONTE, serie.entidade, "silver", p.run_mode,
                         parameters={"codigo": serie.codigo})
    control.iniciar(spark, e)
    c = control.Contagens()
    try:
        filtro = f"serie_codigo = {serie.codigo}"
        src_sql = sql_pendentes(bronze, p.catalogo, FONTE, serie.entidade, filtro, p.run_mode == "reprocess")
        src = spark.sql(src_sql)
        tipado = (src.withColumn("data_referencia", F.expr("try_to_date(data, 'dd/MM/yyyy')"))
                     .withColumn("valor_ok", F.col("valor").rlike(REGEX_VALOR)))
        c.read = tipado.count()
        invalidos = tipado.where("data_referencia IS NULL OR NOT valor_ok OR valor IS NULL")
        c.rejected = quarentena(spark, invalidos.drop("valor_ok"),
                                caminho_quarentena(p.catalogo, FONTE, serie.entidade, hoje, p.run_id),
                                "data ou valor fora do formato da API SGS")
        ultimo = Window.partitionBy("serie_codigo", "data_referencia").orderBy(F.col("_ingestion_timestamp").desc())
        (tipado.where("data_referencia IS NOT NULL AND valor_ok")
               .withColumn("_rn", F.row_number().over(ultimo)).where("_rn = 1")
               .select("serie_codigo", "data_referencia", F.col("valor").cast("decimal(24,8)").alias("valor"))
               .withColumn("record_hash", F.expr(expr_hash(["valor"])))
               .withColumn("_pipeline_run_id", F.lit(p.run_id))
               .createOrReplaceTempView("_sgs_src"))
        n_validos = spark.table("_sgs_src").count()
        c.inserted, c.updated = executar_merge(spark, merge_scd1(destino, "_sgs_src", ["serie_codigo", "data_referencia"], ["valor"]))
        c.unchanged = n_validos - c.inserted - c.updated

        regras = [
            dq.Regra("chave_unica", "Uma linha por (série, data)", "CRITICAL", destino,
                     f"SELECT data_referencia, count(*) n FROM {destino} WHERE {filtro} GROUP BY 1 HAVING n > 1",
                     f"SELECT count(*) FROM {destino} WHERE {filtro}"),
            # Os inválidos já foram para a quarentena; a regra regista-os e bloqueia a gold desta execução.
            dq.Regra("formato_api", "Data e valor da API convertíveis sem perda", "HIGH", bronze,
                     f"SELECT * FROM ({src_sql}) x WHERE try_to_date(data, 'dd/MM/yyyy') IS NULL "
                     f"OR valor IS NULL OR NOT valor rlike '{REGEX_VALOR}'",
                     f"SELECT count(*) FROM ({src_sql}) x"),
        ]
        if not serie.permite_futuro:
            regras.append(dq.Regra("sem_datas_futuras", "Série sem valores com data posterior a hoje", "HIGH", destino,
                                   f"SELECT * FROM {destino} WHERE {filtro} AND data_referencia > current_date()",
                                   f"SELECT count(*) FROM {destino} WHERE {filtro}"))
        resultados = dq.avaliar(spark, regras)
        dq.gravar(spark, p.catalogo, p.run_id, resultados)
        criticas = [r.regra.nome for r in resultados if not r.passou and r.regra.severidade == "CRITICAL"]

        maximo = spark.sql(f"SELECT max(data_referencia) FROM {destino} WHERE {filtro} AND data_referencia <= current_date()").first()[0]
        if maximo and not criticas:
            control.confirmar_watermark(spark, e, "reference_date", maximo.isoformat(), serie.revisao_dias)
        control.concluir(spark, e, c)
        print(f"{serie.entidade}: lidos={c.read} novos={c.inserted} alterados={c.updated} iguais={c.unchanged} "
              f"rejeitados={c.rejected} watermark={maximo} falhas_criticas={criticas}")
        if criticas:
            raise RuntimeError(f"regras críticas falharam em {serie.entidade}: {criticas}")
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        erros[serie.entidade] = repr(ex)

if erros:
    raise RuntimeError(f"falharam {len(erros)} séries: {erros}")
