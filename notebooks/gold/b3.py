# Databricks notebook source
# MAGIC %md
# MAGIC # Gold · B3
# MAGIC - Bloqueia a publicação se a execução tiver falhas de qualidade CRITICAL/HIGH.
# MAGIC - `dim_ativo_b3`: papéis da silver com o emissor da CVM (ações pelo FCA, FII pelo ISIN do informe mensal).
# MAGIC - `fct_cotacao_diaria`: incremental pelo **Change Data Feed** da silver (stream `availableNow` com checkpoint):
# MAGIC   só os tickers alterados são recalculados; `reprocess` reconstrói tudo. Ver docs/streaming.md.
# MAGIC   Desdobramentos e grupamentos são detetados
# MAGIC   quando o fecho varia perto de um fator inteiro (1/2, 1/10, 5, ...) no pregão em que muda o número de
# MAGIC   distribuição do papel; o preço ajustado e o retorno diário descontam esse fator. Dividendos não são ajustados.

# COMMAND ----------

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd().parents[1]))

from src.common import notebook

notebook.declarar(dbutils)
p = notebook.ler(dbutils)
print(p)

# COMMAND ----------

from src.audit import control
from pyspark.sql import functions as F

from src.gold.cotacoes import calculo
from src.quality import rules as dq

k = p.catalogo
e = control.Execucao(k, p.run_id, "gold_b3", "b3", "gold_b3", "gold", p.run_mode)
control.iniciar(spark, e)
bloqueios = dq.falhas_bloqueantes(spark, k, p.run_id)
if bloqueios:
    erro = RuntimeError(f"publicação gold bloqueada por regras de qualidade: {bloqueios}")
    control.falhar(spark, e, erro)
    raise erro

# COMMAND ----------

DIM_ATIVO = f"""
INSERT OVERWRITE {k}.gold.dim_ativo_b3
WITH c AS (
  SELECT ticker, max_by(classe_ativo, data_pregao) AS classe_ativo, max_by(nome_pregao, data_pregao) AS nome_pregao,
         max_by(especificacao, data_pregao) AS especificacao, max_by(isin, data_pregao) AS isin,
         min(data_pregao) AS primeiro_pregao, max(data_pregao) AS ultimo_pregao
  FROM {k}.silver.b3_cotacao_diaria
  WHERE coalesce(especificacao, '') NOT LIKE 'IBO%'   -- IBOV11: cesta do Ibovespa, não é uma ação
  GROUP BY ticker
),
-- O FCA tem tickers mal preenchidos (ex.: CSN declara "4030", BTG "000000", Klabin só KLBN11). Para as ações sem o
-- ticker exato, usa-se a raiz de 4 letras (KLBN4 → KLBN11) quando aponta para uma única companhia.
raiz AS (
  SELECT substr(ticker, 1, 4) AS raiz, max_by(cnpj_cia, data_referencia) AS cnpj_cia,
         max_by(nome_empresarial, data_referencia) AS nome_empresarial,
         max_by(segmento_listagem, data_referencia) AS segmento_listagem
  FROM {k}.silver.cvm_valor_mobiliario WHERE ticker rlike '^[A-Z]{{4}}[0-9]{{1,2}}$'
  GROUP BY 1 HAVING count(DISTINCT cnpj_cia) = 1
),
vm AS (
  SELECT c.ticker, coalesce(v.cnpj_cia, r.cnpj_cia) AS cnpj_cia,
         coalesce(v.nome_empresarial, r.nome_empresarial) AS nome_empresarial,
         coalesce(v.segmento_listagem, r.segmento_listagem) AS segmento_listagem
  FROM c
  LEFT JOIN {k}.silver.cvm_valor_mobiliario v ON v.ticker = c.ticker
  LEFT JOIN raiz r ON r.raiz = substr(c.ticker, 1, 4)
  WHERE c.classe_ativo = 'Ação'
),
fii AS (
  SELECT codigo_isin, max_by(cnpj_classe, data_referencia) AS cnpj, max_by(nome_fundo, data_referencia) AS nome,
         max_by(segmento_atuacao, data_referencia) AS segmento
  FROM {k}.silver.cvm_fii_mensal WHERE codigo_isin IS NOT NULL GROUP BY codigo_isin
),
cia AS (
  SELECT cnpj_cia, max_by(denom_social, dt_reg) AS denom_social, max_by(setor_ativ, dt_reg) AS setor_ativ
  FROM {k}.silver.cvm_companhia WHERE is_current GROUP BY cnpj_cia
)
SELECT c.ticker, c.classe_ativo, c.nome_pregao, c.especificacao, c.isin,
       coalesce(vm.cnpj_cia, fii.cnpj), coalesce(vm.nome_empresarial, cia.denom_social, fii.nome),
       coalesce(cia.setor_ativ, fii.segmento), vm.segmento_listagem,
       -- espécie pela B3: o FCA tem erros (ex.: MGLU3 declarada como preferencial em 2025 e 2026)
       CASE WHEN c.classe_ativo <> 'Ação' THEN NULL WHEN c.especificacao LIKE 'ON%' THEN 'ON'
            WHEN c.especificacao LIKE 'PN%' THEN 'PN' WHEN c.especificacao LIKE 'UNT%' THEN 'Unit' END,
       c.primeiro_pregao, c.ultimo_pregao
FROM c
LEFT JOIN vm ON vm.ticker = c.ticker
LEFT JOIN cia ON cia.cnpj_cia = vm.cnpj_cia
LEFT JOIN fii ON fii.codigo_isin = c.isin AND c.classe_ativo = 'FII'
"""

SILVER = f"{k}.silver.b3_cotacao_diaria"
FCT = f"{k}.gold.fct_cotacao_diaria"
CHECKPOINT = f"/Volumes/{k}/ops/checkpoints/gold_b3_fct_cotacao"


def reconstruir() -> int:
    """Reconstrução completa (reprocess): todo o histórico de todos os tickers."""
    spark.sql(f"INSERT OVERWRITE {FCT} " + calculo(f"SELECT *, DATE'1900-01-01' AS d0 FROM {SILVER}", "true"))
    return spark.table(FCT).count()


def aplicar_alteracoes(lote, lote_id: int) -> None:
    """Um lote do Change Data Feed da silver: recalcula cada ticker alterado desde a primeira data alterada.

    1. d0 = primeira data inserida/alterada do ticker; o cálculo começa no pregão anterior (para o fecho anterior)
       e vai até ao fim da série.
    2. Pregões antes de d0 mantêm-se, mas o preço ajustado é multiplicado por fator_novo / fator_antigo: o produto
       dos fatores de evento no intervalo recalculado, agora e antes (um desdobramento novo reajusta o passado).
    3. MERGE das linhas recalculadas (a silver é SCD1 e nunca apaga, por isso basta inserir/atualizar).
    """
    s = lote.sparkSession
    (lote.where("_change_type IN ('insert', 'update_postimage')")
         .groupBy("ticker").agg(F.min("data_pregao").alias("d0"))
         .createOrReplaceTempView("_cdf_afetados"))
    s.sql(f"""
        SELECT a.ticker, a.d0, coalesce(max(x.data_pregao), a.d0) AS d_ini
        FROM _cdf_afetados a LEFT JOIN {SILVER} x ON x.ticker = a.ticker AND x.data_pregao < a.d0
        GROUP BY a.ticker, a.d0""").createOrReplaceTempView("_cdf_inicio")
    fonte = f"SELECT x.*, i.d0 FROM {SILVER} x JOIN _cdf_inicio i ON x.ticker = i.ticker AND x.data_pregao >= i.d_ini"
    s.sql(calculo(fonte, "data_pregao >= d0")).createOrReplaceTempView("_cdf_novo")
    ajuste = s.sql(f"""
        WITH novo AS (SELECT n.ticker, exp(sum(ln(n.fator_evento))) AS k FROM _cdf_novo n GROUP BY 1),
             antigo AS (SELECT t.ticker, exp(sum(ln(t.fator_evento))) AS k
                        FROM {FCT} t JOIN _cdf_afetados a ON t.ticker = a.ticker AND t.data_pregao >= a.d0
                        GROUP BY 1)
        SELECT a.ticker, a.d0, novo.k / coalesce(antigo.k, 1.0) AS razao
        FROM _cdf_afetados a JOIN novo USING (ticker) LEFT JOIN antigo USING (ticker)
        WHERE abs(novo.k / coalesce(antigo.k, 1.0) - 1) > 1e-12""")
    linhas_ajuste = ajuste.collect()  # poucas linhas; materializa antes de alterar a tabela
    n_ajuste = len(linhas_ajuste)
    if n_ajuste:
        s.createDataFrame(linhas_ajuste).createOrReplaceTempView("_cdf_ajuste")
        s.sql(f"""MERGE INTO {FCT} t USING _cdf_ajuste a ON t.ticker = a.ticker AND t.data_pregao < a.d0
                  WHEN MATCHED THEN UPDATE SET t.preco_ajustado = t.preco_ajustado * a.razao""")
    m = s.sql(f"""MERGE INTO {FCT} t USING _cdf_novo s ON t.ticker = s.ticker AND t.data_key = s.data_key
                  WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *""").first().asDict()
    tickers = s.table("_cdf_afetados").count()
    print(f"lote {lote_id}: {tickers} tickers, {m.get('num_inserted_rows')} linhas novas, "
          f"{m.get('num_updated_rows')} recalculadas, {n_ajuste} tickers com o passado reajustado")


def versao(tabela: str) -> int:
    return spark.sql(f"DESCRIBE HISTORY {tabela} LIMIT 1").first()["version"]


def stream_cdf(desde_ultima: bool = False) -> dict:
    """Corre o stream do CDF até ao fim. As contagens vêm do histórico Delta da gold
    (no serverless o foreachBatch corre noutro processo e não consegue devolver valores ao notebook)."""
    v0 = versao(FCT)
    leitor = spark.readStream.option("readChangeFeed", "true")
    if desde_ultima:
        leitor = leitor.option("startingVersion", "latest")
    q = (leitor.table(SILVER).writeStream.foreachBatch(aplicar_alteracoes)
         .option("checkpointLocation", CHECKPOINT).trigger(availableNow=True)
         .queryName("gold_b3_fct_cotacao").start())
    q.awaitTermination()
    h = spark.sql(f"""
        SELECT count_if(operationParameters.predicate LIKE '%data_key%') AS lotes,
               coalesce(sum(CAST(operationMetrics.numTargetRowsInserted AS BIGINT))
                        FILTER (WHERE operationParameters.predicate LIKE '%data_key%'), 0) AS inseridas,
               coalesce(sum(CAST(operationMetrics.numTargetRowsUpdated AS BIGINT))
                        FILTER (WHERE operationParameters.predicate LIKE '%data_key%'), 0) AS recalculadas,
               coalesce(sum(CAST(operationMetrics.numTargetRowsUpdated AS BIGINT))
                        FILTER (WHERE operationParameters.predicate NOT LIKE '%data_key%'), 0) AS passado_reajustado
        FROM (DESCRIBE HISTORY {FCT}) WHERE version > {v0} AND operation = 'MERGE'""").first().asDict()
    return h


contagens = control.Contagens()
fct_stats = {"lotes": 0, "inseridas": 0, "recalculadas": 0, "passado_reajustado": 0}
try:
    spark.sql(DIM_ATIVO)
    n = spark.table(f"{k}.gold.dim_ativo_b3").count()
    contagens.inserted += n
    print(f"gold.dim_ativo_b3: {n} linhas")

    if p.run_mode == "reprocess":
        # recomeça o stream do zero: reconstrói tudo e o checkpoint novo só lê alterações posteriores
        dbutils.fs.rm(CHECKPOINT, True)
        print(f"gold.fct_cotacao_diaria: reconstruída, {reconstruir()} linhas")
        fct_stats = stream_cdf(desde_ultima=True)
    else:
        # Na primeira execução (sem checkpoint) o Change Data Feed entrega a silver inteira como inserts, o que
        # equivale a uma reconstrução; depois, só as alterações desde a última execução.
        fct_stats = stream_cdf()
        print(f"gold.fct_cotacao_diaria (Change Data Feed): {fct_stats}")
    contagens.inserted += fct_stats["inseridas"]
    contagens.updated += fct_stats["recalculadas"]
    e.parameters = {**(e.parameters or {}), "change_data_feed": fct_stats}

    fct, dim = f"{k}.gold.fct_cotacao_diaria", f"{k}.gold.dim_ativo_b3"
    regras = [
        dq.Regra("fct_cotacao_chave_unica", "Uma linha por (ticker, pregão)", "CRITICAL", fct,
                 f"SELECT ticker, data_key, count(*) n FROM {fct} GROUP BY ALL HAVING n > 1",
                 f"SELECT count(*) FROM {fct}"),
        dq.Regra("dim_ativo_chave_unica", "Um registo por ticker", "CRITICAL", dim,
                 f"SELECT ticker, count(*) n FROM {dim} GROUP BY 1 HAVING n > 1", f"SELECT count(*) FROM {dim}"),
        # Só para revisão: os eventos detetados pela heurística (desdobramentos e grupamentos)
        dq.Regra("eventos_detetados", "Desdobramentos/grupamentos detetados (fator aplicado ao preço ajustado)", "INFO",
                 fct, f"SELECT ticker, data_pregao, fator_evento FROM {fct} WHERE fator_evento <> 1 "
                      f"ORDER BY data_pregao DESC", f"SELECT count(DISTINCT ticker) FROM {fct}"),
        dq.Regra("retorno_diario_extremo", "Retorno diário acima de ±50 % depois do ajuste (evento não detetado?)",
                 "INFO", fct, f"SELECT ticker, data_pregao, retorno_dia FROM {fct} WHERE abs(retorno_dia) > 0.5 "
                              f"ORDER BY data_pregao DESC", f"SELECT count(*) FROM {fct} WHERE retorno_dia IS NOT NULL"),
        dq.Regra("acao_sem_emissor", "Ação negociada no último mês sem companhia no FCA da CVM", "INFO", dim,
                 f"SELECT ticker, nome_pregao FROM {dim} WHERE classe_ativo = 'Ação' AND cnpj_emissor IS NULL "
                 f"AND ultimo_pregao >= add_months(current_date(), -1)",
                 f"SELECT count(*) FROM {dim} WHERE classe_ativo = 'Ação' AND ultimo_pregao >= add_months(current_date(), -1)"),
    ]
    resultados = dq.avaliar(spark, regras, amostra=10)
    dq.gravar(spark, k, p.run_id, resultados)
    for r in resultados:
        print(f"{r.regra.nome}: {'PASSED' if r.passou else 'FAILED'} ({r.falhados}/{r.avaliados}) {r.amostra[:5]}")
    criticas = [r.regra.nome for r in resultados if not r.passou and r.regra.severidade == "CRITICAL"]
    if criticas:
        raise RuntimeError(f"regras críticas falharam na gold: {criticas}")
    control.concluir(spark, e, contagens)
except Exception as ex:
    control.falhar(spark, e, ex, contagens)
    raise

# COMMAND ----------

display(spark.sql(f"SELECT * FROM {k}.gold.vw_b3_desempenho WHERE classe_ativo = 'Ação' "
                  f"ORDER BY volume_medio_diario DESC LIMIT 20"))
