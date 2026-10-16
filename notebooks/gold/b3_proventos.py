# Databricks notebook source
# MAGIC %md
# MAGIC # Gold · B3 proventos
# MAGIC - `fct_provento`: proventos da silver ligados ao ticker (raiz do emissor + espécie), com data ex, yield do evento
# MAGIC   (valor / fecho na data com) e valor ajustado a desdobramentos posteriores (mesmos fatores da
# MAGIC   `fct_cotacao_diaria`). Reconstrução completa (dezenas de milhares de linhas).
# MAGIC - Compara os desdobramentos/grupamentos detetados pela heurística da gold com os oficiais da B3 (regra INFO).

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
from src.quality import rules as dq

k = p.catalogo
e = control.Execucao(k, p.run_id, "gold_b3_proventos", "b3", "gold_b3_proventos", "gold", p.run_mode)
control.iniciar(spark, e)
bloqueios = dq.falhas_bloqueantes(spark, k, p.run_id)
if bloqueios:
    erro = RuntimeError(f"publicação gold bloqueada por regras de qualidade: {bloqueios}")
    control.falhar(spark, e, erro)
    raise erro

FCT_PROVENTO = f"""
INSERT OVERWRITE {k}.gold.fct_provento
WITH papel AS (
  -- espécie do ticker = primeira palavra da especificação da B3 (ON NM → ON, PNA N1 → PNA, UNT N2 → UNT)
  SELECT ticker, substr(ticker, 1, 4) AS emissor, split(especificacao, ' ')[0] AS tipo_acao
  FROM {k}.gold.dim_ativo_b3 WHERE classe_ativo = 'Ação'
),
p AS (
  SELECT pa.ticker, s.* FROM {k}.silver.b3_provento s
  JOIN papel pa ON pa.emissor = s.emissor AND pa.tipo_acao = s.tipo_acao
),
c AS (SELECT ticker, data_pregao, preco_fechamento, fator_evento FROM {k}.gold.fct_cotacao_diaria)
SELECT p.ticker, p.emissor, p.tipo_acao, p.tipo_provento, p.data_com,
       (SELECT min(c.data_pregao) FROM c WHERE c.ticker = p.ticker AND c.data_pregao > p.data_com),
       p.data_aprovacao, p.valor_por_acao,
       (SELECT max_by(c.preco_fechamento, c.data_pregao) FROM c WHERE c.ticker = p.ticker AND c.data_pregao <= p.data_com),
       NULL, NULL, NULL
FROM p
"""

COMPLETAR = f"""
MERGE INTO {k}.gold.fct_provento t
USING (
  SELECT f.ticker, f.tipo_provento, f.data_com, f.valor_por_acao,
         CAST(f.valor_por_acao AS DOUBLE) / nullif(CAST(f.fecho_data_com AS DOUBLE), 0) AS yield_evento,
         coalesce(exp(sum(ln(c.fator_evento))), 1.0) AS fator_posterior
  FROM {k}.gold.fct_provento f
  LEFT JOIN {k}.gold.fct_cotacao_diaria c ON c.ticker = f.ticker AND c.data_pregao > f.data_com AND c.fator_evento <> 1
  GROUP BY ALL
) s ON t.ticker = s.ticker AND t.tipo_provento = s.tipo_provento AND t.data_com = s.data_com
   AND t.valor_por_acao = s.valor_por_acao
WHEN MATCHED THEN UPDATE SET t.yield_evento = s.yield_evento, t.fator_posterior = s.fator_posterior,
                             t.valor_ajustado = CAST(t.valor_por_acao AS DOUBLE) * s.fator_posterior
"""

contagens = control.Contagens()
try:
    spark.sql(FCT_PROVENTO)
    spark.sql(COMPLETAR)
    n = spark.table(f"{k}.gold.fct_provento").count()
    contagens.inserted = n
    print(f"gold.fct_provento: {n} linhas")

    fct = f"{k}.gold.fct_provento"
    regras = [
        dq.Regra("fct_provento_chave_unica", "Uma linha por (ticker, tipo, data com, valor)", "CRITICAL", fct,
                 f"SELECT ticker, tipo_provento, data_com, valor_por_acao, count(*) n FROM {fct} GROUP BY ALL HAVING n > 1",
                 f"SELECT count(*) FROM {fct}"),
        dq.Regra("provento_sem_ticker", "Proventos de emissores ativos sem ticker correspondente (espécie desconhecida)",
                 "INFO", f"{k}.silver.b3_provento",
                 f"""SELECT s.emissor, s.tipo_acao, count(*) AS n FROM {k}.silver.b3_provento s
                     LEFT ANTI JOIN {fct} f ON f.emissor = s.emissor AND f.tipo_acao = s.tipo_acao
                     WHERE s.data_com >= DATE'2021-01-01' GROUP BY ALL ORDER BY n DESC""",
                 f"SELECT count(DISTINCT emissor, tipo_acao) FROM {k}.silver.b3_provento"),
        dq.Regra("yield_evento_suspeito", "Yield de um evento acima de 30 % (valor ou preço errado?)", "INFO", fct,
                 f"SELECT ticker, data_com, valor_por_acao, fecho_data_com, yield_evento FROM {fct} "
                 f"WHERE yield_evento > 0.3", f"SELECT count(*) FROM {fct}"),
        # Desdobramentos/grupamentos oficiais (B3) desde 2021 que a heurística da fct_cotacao_diaria não detetou
        dq.Regra("evento_oficial_nao_detetado", "Desdobramento/grupamento oficial sem fator detetado nos 5 pregões "
                 "seguintes à data com", "INFO", f"{k}.silver.b3_evento_acao",
                 f"""SELECT a.ticker, o.tipo_evento, o.data_com, o.fator
                     FROM {k}.silver.b3_evento_acao o
                     JOIN {k}.gold.dim_ativo_b3 a ON a.isin = o.isin
                     WHERE o.tipo_evento IN ('DESDOBRAMENTO', 'GRUPAMENTO') AND o.data_com >= DATE'2021-01-04'
                       AND o.data_com < (SELECT max(data_pregao) FROM {k}.gold.fct_cotacao_diaria)
                       AND NOT EXISTS (SELECT 1 FROM {k}.gold.fct_cotacao_diaria c
                                       WHERE c.ticker = a.ticker AND c.fator_evento <> 1
                                         AND c.data_pregao > o.data_com AND c.data_pregao <= date_add(o.data_com, 7))""",
                 f"""SELECT count(*) FROM {k}.silver.b3_evento_acao o JOIN {k}.gold.dim_ativo_b3 a ON a.isin = o.isin
                     WHERE o.tipo_evento IN ('DESDOBRAMENTO', 'GRUPAMENTO') AND o.data_com >= DATE'2021-01-04'"""),
    ]
    resultados = dq.avaliar(spark, regras, amostra=10)
    dq.gravar(spark, k, p.run_id, resultados)
    for r in resultados:
        print(f"{r.regra.nome}: {'PASSED' if r.passou else 'FAILED'} ({r.falhados}/{r.avaliados}) {r.amostra[:5]}")
    if any(not r.passou and r.regra.severidade == "CRITICAL" for r in resultados):
        raise RuntimeError("regras críticas falharam na gold de proventos")
    control.concluir(spark, e, contagens)
except Exception as ex:
    control.falhar(spark, e, ex, contagens)
    raise
