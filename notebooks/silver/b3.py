# Databricks notebook source
# MAGIC %md
# MAGIC # Silver · B3
# MAGIC `b3_cotacao_diaria` (SCD1, uma linha por pregão e ticker): só os códigos BDI de `classes_silver`
# MAGIC (lote padrão, FII, ETF e fundos). Converte as casas decimais implícitas, divide pelo fator de cotação e rejeita
# MAGIC para quarentena o que não converte. O mesmo pregão pode chegar no anual e no diário: fica a carga mais recente.

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

from src.audit import control
from src.common.config import carregar_yaml
from src.quality import rules as dq
from src.scd.merge_sql import expr_hash, merge_scd1
from src.silver.common import caminho_quarentena, executar_merge, sql_pendentes

FONTE, ENTIDADE = "b3", "cotahist"
k = p.catalogo
cfg = carregar_yaml("datasets/b3.yaml")["cotahist"]
hoje = date.today()
bronze = f"{k}.bronze.{cfg['tabela_bronze']}"
destino = f"{k}.silver.b3_cotacao_diaria"
classes = cfg["classes_silver"]


def digitos(c: str) -> str:
    return f"({c} rlike '^[0-9]+$')"


def dec(c: str, casas: int = 2) -> str:
    """Campo com casas implícitas → DECIMAL; dividido pelo fator de cotação (preço por unidade)."""
    return f"CAST(CAST({c} AS DECIMAL(24, 0)) / {10 ** casas} / CAST(fatcot AS INT) AS DECIMAL(18, 6))"


# COMMAND ----------

if p.escolhida(ENTIDADE):
    e = control.Execucao(k, p.run_id, "silver_b3", FONTE, ENTIDADE, "silver", p.run_mode)
    control.iniciar(spark, e)
    c = control.Contagens()
    try:
        filtro = f"codbdi IN ({', '.join(repr(x) for x in classes)})"
        pend = sql_pendentes(bronze, k, FONTE, ENTIDADE, filtro, p.run_mode == "reprocess")
        valido = " AND ".join([
            "to_date(data_pregao, 'yyyyMMdd') IS NOT NULL", "nullif(codneg, '') IS NOT NULL",
            *(digitos(x) for x in ("preabe", "premax", "premin", "premed", "preult", "totneg", "quatot", "voltot",
                                   "fatcot", "dismes")),
            "CAST(fatcot AS INT) > 0",
        ])
        spark.sql(f"SELECT *, coalesce(({valido}), false) AS _valido FROM ({pend})").createOrReplaceTempView("_b3_pend")
        c.read = spark.table("_b3_pend").count()
        invalidos = spark.table("_b3_pend").where("NOT _valido").drop("_valido")
        c.rejected = invalidos.count()
        if c.rejected:
            invalidos.write.mode("append").json(caminho_quarentena(k, FONTE, ENTIDADE, hoje, p.run_id))
        classe_sql = "CASE codbdi " + " ".join(f"WHEN '{b}' THEN '{n}'" for b, n in classes.items()) + " END"
        colunas = ["codbdi", "classe_ativo", "nome_pregao", "especificacao", "isin", "distribuicao", "preco_abertura",
                   "preco_maximo", "preco_minimo", "preco_medio", "preco_fechamento", "negocios", "quantidade",
                   "volume", "fator_cotacao"]
        spark.sql(f"""
            SELECT data_pregao, ticker, {', '.join(colunas)},
                   {expr_hash(colunas)} AS record_hash, '{p.run_id}' AS _pipeline_run_id
            FROM (
              SELECT to_date(data_pregao, 'yyyyMMdd') AS data_pregao, codneg AS ticker, codbdi,
                     {classe_sql} AS classe_ativo, nullif(nomres, '') AS nome_pregao,
                     nullif(regexp_replace(especi, ' +', ' '), '') AS especificacao, nullif(codisi, '') AS isin,
                     CAST(dismes AS INT) AS distribuicao,
                     {dec('preabe')} AS preco_abertura, {dec('premax')} AS preco_maximo, {dec('premin')} AS preco_minimo,
                     {dec('premed')} AS preco_medio, {dec('preult')} AS preco_fechamento,
                     CAST(totneg AS INT) AS negocios, CAST(quatot AS BIGINT) AS quantidade,
                     CAST(CAST(voltot AS DECIMAL(24, 0)) / 100 AS DECIMAL(20, 2)) AS volume,
                     CAST(fatcot AS INT) AS fator_cotacao, _ingestion_timestamp, _record_hash
              FROM _b3_pend WHERE _valido
            )
            -- o mesmo pregão chega no ficheiro anual e no diário: fica a carga mais recente
            QUALIFY row_number() OVER (PARTITION BY data_pregao, ticker
                                       ORDER BY _ingestion_timestamp DESC, _record_hash) = 1
        """).createOrReplaceTempView("_b3_src")
        n_validos = spark.table("_b3_src").count()
        c.inserted, c.updated = executar_merge(spark, merge_scd1(destino, "_b3_src", ["data_pregao", "ticker"], colunas))
        c.unchanged = n_validos - c.inserted - c.updated

        da_execucao = f"SELECT * FROM {destino} WHERE _pipeline_run_id = '{p.run_id}'"
        total_exec = f"SELECT count(*) FROM ({da_execucao})"
        regras = [
            dq.Regra("chave_unica", "Uma linha por (pregão, ticker)", "CRITICAL", destino,
                     f"SELECT data_pregao, ticker, count(*) n FROM {destino} GROUP BY ALL HAVING n > 1",
                     f"SELECT count(*) FROM {destino}"),
            dq.Regra("formato_layout", "Data e campos numéricos do layout COTAHIST convertíveis", "HIGH", bronze,
                     "SELECT * FROM _b3_pend WHERE NOT _valido", "SELECT count(*) FROM _b3_pend"),
            dq.Regra("data_nao_futura", "Pregão não posterior a hoje", "HIGH", destino,
                     f"SELECT * FROM ({da_execucao}) WHERE data_pregao > current_date()", total_exec),
            dq.Regra("preco_positivo", "Preço de fecho maior que zero", "INFO", destino,
                     f"SELECT data_pregao, ticker, preco_fechamento FROM ({da_execucao}) WHERE preco_fechamento <= 0",
                     total_exec),
            dq.Regra("fecho_entre_minimo_e_maximo", "Mínimo <= fecho <= máximo", "INFO", destino,
                     f"SELECT data_pregao, ticker, preco_minimo, preco_fechamento, preco_maximo FROM ({da_execucao}) "
                     f"WHERE preco_fechamento < preco_minimo OR preco_fechamento > preco_maximo", total_exec),
        ]
        resultados = dq.avaliar(spark, regras)
        dq.gravar(spark, k, p.run_id, resultados)
        criticas = [r.regra.nome for r in resultados if not r.passou and r.regra.severidade == "CRITICAL"]
        maximo = spark.sql(f"SELECT max(data_pregao) FROM {destino}").first()[0]
        if maximo and not criticas:
            control.confirmar_watermark(spark, e, "reference_date", maximo.isoformat(), None)
        control.concluir(spark, e, c)
        print(f"cotahist: lidos={c.read} novos={c.inserted} alterados={c.updated} iguais={c.unchanged} "
              f"rejeitados={c.rejected} watermark={maximo} falhas={[r.regra.nome for r in resultados if not r.passou]}")
        if criticas:
            raise RuntimeError(f"regras críticas falharam: {criticas}")
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        raise
