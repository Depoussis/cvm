# Databricks notebook source
# MAGIC %md
# MAGIC # Gold · B3
# MAGIC - Bloqueia a publicação se a execução tiver falhas de qualidade CRITICAL/HIGH.
# MAGIC - `dim_ativo_b3`: papéis da silver com o emissor da CVM (ações pelo FCA, FII pelo ISIN do informe mensal).
# MAGIC - `fct_cotacao_diaria`: reconstrução completa (~1 milhão de linhas). Desdobramentos e grupamentos são detetados
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

FCT_COTACAO = f"""
INSERT OVERWRITE {k}.gold.fct_cotacao_diaria
WITH b AS (
  SELECT s.*, lag(preco_fechamento) OVER w AS fecho_anterior, lag(distribuicao) OVER w AS distribuicao_anterior
  FROM {k}.silver.b3_cotacao_diaria s
  WHERE coalesce(especificacao, '') NOT LIKE 'IBO%'
  WINDOW w AS (PARTITION BY ticker ORDER BY data_pregao)
),
r AS (
  SELECT b.*,
         CASE WHEN fecho_anterior > 0 AND preco_fechamento > 0
              THEN CAST(preco_fechamento AS DOUBLE) / CAST(fecho_anterior AS DOUBLE) END AS razao
  FROM b
),
cand AS (
  -- fator inteiro mais próximo: 1/k para desdobramentos (preço cai k vezes), k para grupamentos
  SELECT r.*, CASE WHEN razao < 0.6 THEN 1.0 / round(1.0 / razao)
                   WHEN razao > 1.6 THEN round(razao) END AS candidato
  FROM r
),
f AS (
  SELECT cand.*,
         CASE WHEN candidato BETWEEN 0.001 AND 1000 AND distribuicao <> distribuicao_anterior
                   AND abs(razao / candidato - 1) <= 0.08 THEN CAST(candidato AS DOUBLE) ELSE 1.0 END AS fator_evento
  FROM cand
)
SELECT ticker, data_pregao, CAST(date_format(data_pregao, 'yyyyMMdd') AS INT), classe_ativo, preco_abertura,
       preco_maximo, preco_minimo, preco_fechamento, negocios, quantidade, volume, fator_evento,
       razao / fator_evento - 1,
       CAST(preco_fechamento AS DOUBLE) * coalesce(exp(sum(ln(fator_evento)) OVER (
         PARTITION BY ticker ORDER BY data_pregao ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING)), 1.0)
FROM f
"""

contagens = control.Contagens()
try:
    for nome, sql in (("dim_ativo_b3", DIM_ATIVO), ("fct_cotacao_diaria", FCT_COTACAO)):
        spark.sql(sql)
        n = spark.table(f"{k}.gold.{nome}").count()
        contagens.inserted += n
        print(f"gold.{nome}: {n} linhas")

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
