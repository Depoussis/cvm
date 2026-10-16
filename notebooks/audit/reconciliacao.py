# Databricks notebook source
# MAGIC %md
# MAGIC # Auditoria · Reconciliação com a fonte
# MAGIC Compara a silver com a fonte e grava o resultado em `control.reconciliation_results`.
# MAGIC - **BCB SGS e PTAX:** volta a pedir o histórico completo à API (mesmas janelas da ingestão) e compara chave a
# MAGIC   chave: só na fonte, só na plataforma e valores diferentes.
# MAGIC - **CVM informe diário:** por mês, verifica com `HEAD` se o ficheiro na fonte ainda é o último carregado (ETag) e
# MAGIC   compara as chaves/valores desse ficheiro (bronze) com a silver. Linhas que a CVM retirou numa republicação
# MAGIC   aparecem como "só na plataforma" (o SCD1 não apaga).
# MAGIC Entidades: `bcb_sgs`, `bcb_ptax`, `cvm`. Agendado semanalmente (job `findata_<env>_auditoria`).

# COMMAND ----------

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd().parents[1]))

from src.common import notebook

notebook.declarar(dbutils)
p = notebook.ler(dbutils)
print(p)

# COMMAND ----------

import json
import uuid
from datetime import date

from pyspark.sql import functions as F

from src.audit import control
from src.common.config import carregar_yaml
from src.common.http import ClienteHttp
from src.ingestion.bcb_ptax import client as ptax
from src.ingestion.bcb_sgs.client import Serie, converter_data, extrair
from src.ingestion.cvm import files as cvm

k = p.catalogo
hoje = date.today()
fonte_bcb = carregar_yaml("sources/bcb.yaml")
cliente = ClienteHttp(fonte_bcb["http"])
resultados = []


def comparar(fonte_view: str, plataforma_sql: str, chaves: list[str], valores: list[str]) -> dict:
    """Contagens de divergência entre duas relações com as mesmas colunas (chaves + valores)."""
    spark.sql(plataforma_sql).createOrReplaceTempView("_plat")
    on = " AND ".join(f"f.{c} <=> p.{c}" for c in chaves)
    dif = " OR ".join(f"NOT (f.{c} <=> p.{c})" for c in valores)
    r = spark.sql(f"""
        SELECT (SELECT count(*) FROM {fonte_view}) AS registos_fonte,
               (SELECT count(*) FROM _plat) AS registos_plataforma,
               (SELECT count(*) FROM {fonte_view} f LEFT ANTI JOIN _plat p ON {on}) AS so_na_fonte,
               (SELECT count(*) FROM _plat p LEFT ANTI JOIN {fonte_view} f ON {on}) AS so_na_plataforma,
               (SELECT count(*) FROM {fonte_view} f JOIN _plat p ON {on} WHERE ({dif})) AS valores_diferentes
    """).first().asDict()
    amostra = spark.sql(f"""
        SELECT * FROM (SELECT 'valor' AS tipo, to_json(struct(f.*)) AS fonte, to_json(struct(p.*)) AS plataforma
                       FROM {fonte_view} f JOIN _plat p ON {on} WHERE ({dif}) LIMIT 3)
        UNION ALL
        SELECT * FROM (SELECT 'so_na_fonte', to_json(struct(f.*)), CAST(NULL AS STRING)
                       FROM {fonte_view} f LEFT ANTI JOIN _plat p ON {on} LIMIT 3)
        UNION ALL
        SELECT * FROM (SELECT 'so_na_plataforma', CAST(NULL AS STRING), to_json(struct(p.*))
                       FROM _plat p LEFT ANTI JOIN {fonte_view} f ON {on} LIMIT 3)
    """).collect()
    r["detalhe"] = json.dumps([x.asDict() for x in amostra], ensure_ascii=False)[:4000] if amostra else None
    return r


def registar(source_system: str, entidade: str, periodo: str, r: dict | None, erro: str | None = None,
             resultado: str | None = None) -> None:
    divergente = r and (r["so_na_fonte"] or r["so_na_plataforma"] or r["valores_diferentes"])
    resultados.append({
        "reconciliation_id": uuid.uuid4().hex, "pipeline_run_id": p.run_id, "source_system": source_system,
        "entity_name": entidade, "periodo": periodo,
        **({k_: r[k_] for k_ in ("registos_fonte", "registos_plataforma", "so_na_fonte", "so_na_plataforma",
                                  "valores_diferentes")} if r else
           dict.fromkeys(("registos_fonte", "registos_plataforma", "so_na_fonte", "so_na_plataforma", "valores_diferentes"))),
        "resultado": resultado or ("ERRO" if erro else ("DIVERGENTE" if divergente else "OK")),
        "detalhe": erro[:4000] if erro else (r or {}).get("detalhe"),
        "executed_at": control.agora_utc(),
    })
    estado = resultados[-1]["resultado"]
    print(f"{source_system}/{entidade} {periodo}: {estado} {'' if not r else {x: r[x] for x in r if x != 'detalhe'}}")

# COMMAND ----------

# MAGIC %md ## BCB SGS

# COMMAND ----------

if p.escolhida("bcb_sgs"):
    for s in [Serie.de_config(x) for x in carregar_yaml("series/bcb_sgs.yaml")["series"]]:
        try:
            linhas = [(s.codigo, converter_data(r["data"]), r["valor"])
                      for pg in extrair(cliente, fonte_bcb["bcb_sgs"]["url"], s, s.inicio_backfill, hoje,
                                        fonte_bcb["bcb_sgs"]["janela_max_anos"])
                      for r in pg.registos]
            (spark.createDataFrame(linhas, "serie_codigo INT, data_referencia DATE, valor STRING")
                  .where(F.col("data_referencia") <= F.lit(hoje))
                  .dropDuplicates(["serie_codigo", "data_referencia"])
                  .withColumn("valor", F.col("valor").cast("decimal(24,8)"))
                  .createOrReplaceTempView("_fonte"))
            r = comparar("_fonte", f"""SELECT serie_codigo, data_referencia, valor FROM {k}.silver.bcb_sgs_valores
                                       WHERE serie_codigo = {s.codigo} AND data_referencia >= DATE'{s.inicio_backfill}'
                                       AND data_referencia <= DATE'{hoje}'""",
                         ["serie_codigo", "data_referencia"], ["valor"])
            registar("bcb_sgs", s.entidade, f"{s.inicio_backfill}/{hoje}", r)
        except Exception as ex:
            registar("bcb_sgs", s.entidade, None, None, repr(ex))

# COMMAND ----------

# MAGIC %md ## BCB PTAX

# COMMAND ----------

if p.escolhida("bcb_ptax"):
    cfg_p = fonte_bcb["bcb_ptax"]
    inicio = date.fromisoformat(str(cfg_p["inicio_backfill"]))
    num = "decimal(24,8)"
    for moeda in cfg_p["moedas"]:
        try:
            linhas = [(moeda, r["dataHoraCotacao"], r["tipoBoletim"], r["cotacaoCompra"], r["cotacaoVenda"],
                       r["paridadeCompra"], r["paridadeVenda"])
                      for pg in ptax.extrair_cotacoes(cliente, cfg_p["url_cotacoes"], moeda, inicio, hoje,
                                                      cfg_p["janela_max_dias"])
                      for r in pg.registos]
            (spark.createDataFrame(linhas, "moeda STRING, dh STRING, tipo_boletim STRING, cotacao_compra STRING, "
                                           "cotacao_venda STRING, paridade_compra STRING, paridade_venda STRING")
                  .selectExpr("moeda", "CAST(dh AS TIMESTAMP) AS data_hora_cotacao", "tipo_boletim",
                              *[f"CAST({c} AS {num}) AS {c}" for c in
                                ("cotacao_compra", "cotacao_venda", "paridade_compra", "paridade_venda")])
                  .dropDuplicates(["moeda", "data_hora_cotacao", "tipo_boletim"])
                  .createOrReplaceTempView("_fonte"))
            r = comparar("_fonte", f"""SELECT moeda, data_hora_cotacao, tipo_boletim, cotacao_compra, cotacao_venda,
                                              paridade_compra, paridade_venda
                                       FROM {k}.silver.bcb_ptax_cotacoes WHERE moeda = '{moeda}'
                                       AND data_cotacao BETWEEN DATE'{inicio}' AND DATE'{hoje}'""",
                         ["moeda", "data_hora_cotacao", "tipo_boletim"],
                         ["cotacao_compra", "cotacao_venda", "paridade_compra", "paridade_venda"])
            registar("bcb_ptax", f"cotacao_{moeda}", f"{inicio}/{hoje}", r)
        except Exception as ex:
            registar("bcb_ptax", f"cotacao_{moeda}", None, None, repr(ex))

# COMMAND ----------

# MAGIC %md ## CVM informe diário

# COMMAND ----------

if p.escolhida("cvm"):
    ultimos = spark.sql(f"""
        SELECT reference_period, source_url, source_etag, file_hash_sha256
        FROM {k}.control.source_file_registry
        WHERE source_system = 'cvm' AND entity_name = 'fi_inf_diario' AND processing_status = 'PROCESSED'
        QUALIFY row_number() OVER (PARTITION BY reference_period ORDER BY received_at DESC) = 1
        ORDER BY reference_period""").collect()
    cnpj = "regexp_replace(coalesce(cnpj_fundo_classe, cnpj_fundo), '[^0-9]', '')"
    for f in ultimos:
        periodo = f.reference_period
        try:
            h = cliente.head(f.source_url)
            if h.etag and f.source_etag and h.etag != f.source_etag:
                registar("cvm", "fi_inf_diario", periodo, None,
                         f"a fonte publicou uma versão nova (ETag {h.etag}, carregado {f.source_etag}); "
                         f"corre o incremental antes de reconciliar", resultado="FONTE_ATUALIZADA")
                continue
            spark.sql(f"""
                SELECT {cnpj} AS cnpj_classe, coalesce(nullif(trim(id_subclasse), ''), '') AS id_subclasse,
                       try_to_date(dt_comptc, 'yyyy-MM-dd') AS dt_comptc,
                       CAST(nullif(trim(vl_quota), '') AS DECIMAL(27,12)) AS vl_quota,
                       CAST(nullif(trim(vl_patrim_liq), '') AS DECIMAL(17,2)) AS vl_patrim_liq,
                       CAST(nullif(trim(nr_cotst), '') AS INT) AS nr_cotst
                FROM {k}.bronze.cvm_fi_inf_diario WHERE _file_hash = '{f.file_hash_sha256}' AND _corrupt_record IS NULL
                -- mesmo desempate da silver para chaves repetidas no ficheiro (FI vs CLASSES - FIF)
                QUALIFY row_number() OVER (PARTITION BY cnpj_classe, id_subclasse, dt_comptc
                    ORDER BY CASE WHEN coalesce(tp_fundo_classe, tp_fundo) LIKE 'CLASSE%' THEN 0 ELSE 1 END,
                             _record_hash) = 1
            """).createOrReplaceTempView("_fonte")
            r = comparar("_fonte", f"""SELECT cnpj_classe, id_subclasse, dt_comptc, vl_quota, vl_patrim_liq, nr_cotst
                                       FROM {k}.silver.cvm_fi_informe_diario
                                       WHERE date_format(dt_comptc, 'yyyy-MM') = '{periodo}'""",
                         ["cnpj_classe", "id_subclasse", "dt_comptc"], ["vl_quota", "vl_patrim_liq", "nr_cotst"])
            registar("cvm", "fi_inf_diario", periodo, r)
        except Exception as ex:
            registar("cvm", "fi_inf_diario", periodo, None, repr(ex))

# COMMAND ----------

tabela = f"{k}.control.reconciliation_results"
if resultados:
    spark.createDataFrame(resultados, schema=spark.table(tabela).schema).write.mode("append").saveAsTable(tabela)
    # Marca a última reconciliação completa nas entidades sem divergências
    ok = [(x["source_system"], x["entity_name"]) for x in resultados if x["resultado"] == "OK"]
    falhas = {(x["source_system"], x["entity_name"]) for x in resultados if x["resultado"] != "OK"}
    for s_, e_ in sorted(set(ok) - falhas):
        spark.sql(f"""UPDATE {k}.control.ingestion_watermark SET last_full_reconciliation = current_timestamp()
                      WHERE source_system = :s AND entity_name = :e""", args={"s": s_, "e": e_})
display(spark.sql(f"""SELECT source_system, entity_name, periodo, resultado, registos_fonte, registos_plataforma,
                             so_na_fonte, so_na_plataforma, valores_diferentes
                      FROM {tabela} WHERE pipeline_run_id = '{p.run_id}' ORDER BY 1, 2, 3"""))
erros = [x for x in resultados if x["resultado"] == "ERRO"]
if erros:
    raise RuntimeError(f"{len(erros)} reconciliações com erro: {[(x['entity_name'], x['periodo']) for x in erros]}")
