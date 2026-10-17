-- Acompanhamento ao vivo do modelo de ranking: para cada ranking publicado (gold.ml_ranking_historico), o retorno
-- total de cada ação nos 21 pregões seguintes, com a mesma definição do alvo do modelo (src/ml/features.py):
-- (preço ajustado no fim + proventos ajustados com data ex na janela) / preço ajustado na data do ranking - 1.
-- Enquanto não passam 21 pregões, mostra o retorno até ao último pregão (concluido = false).
-- Inclui uma linha de referência BOVA11 (posicao NULL) por ranking.

CREATE OR REPLACE VIEW ${catalog}.gold.vw_ml_acompanhamento
COMMENT 'Modelo de ranking: retorno realizado de cada ranking publicado nos 21 pregões seguintes (ao vivo)'
AS
WITH h AS (
  SELECT data_ref, ticker, setor, score, posicao, modelo, publicado_em FROM ${catalog}.gold.ml_ranking_historico
  UNION ALL
  SELECT DISTINCT data_ref, 'BOVA11', 'Referência', CAST(NULL AS DOUBLE), CAST(NULL AS INT), modelo, publicado_em
  FROM ${catalog}.gold.ml_ranking_historico
),
pares AS (SELECT DISTINCT data_ref, ticker FROM h),
depois AS (       -- pregões do próprio papel depois da data do ranking
  SELECT p.data_ref, p.ticker, c.data_pregao, c.preco_ajustado,
         row_number() OVER (PARTITION BY p.data_ref, p.ticker ORDER BY c.data_pregao) AS n
  FROM pares p JOIN ${catalog}.gold.fct_cotacao_diaria c ON c.ticker = p.ticker AND c.data_pregao > p.data_ref
),
fim AS (
  SELECT data_ref, ticker, max(n) AS pregoes, max_by(data_pregao, n) AS data_fim, max_by(preco_ajustado, n) AS p_fim
  FROM depois WHERE n <= 21 GROUP BY data_ref, ticker
),
ini AS (
  SELECT p.data_ref, p.ticker, max_by(c.preco_ajustado, c.data_pregao) AS p_ini
  FROM pares p JOIN ${catalog}.gold.fct_cotacao_diaria c
    ON c.ticker = p.ticker AND c.data_pregao <= p.data_ref AND c.data_pregao > date_sub(p.data_ref, 10)
  GROUP BY p.data_ref, p.ticker
),
div AS (
  SELECT f.data_ref, f.ticker, sum(pr.valor_ajustado) AS div
  FROM fim f JOIN ${catalog}.gold.fct_provento pr
    ON pr.ticker = f.ticker AND pr.data_ex > f.data_ref AND pr.data_ex <= f.data_fim
  GROUP BY f.data_ref, f.ticker
)
SELECT h.data_ref, h.ticker, h.setor, h.score, h.posicao, h.modelo, h.publicado_em,
       coalesce(f.pregoes, 0) AS pregoes, f.data_fim, coalesce(f.pregoes, 0) >= 21 AS concluido,
       CAST(i.p_ini AS DOUBLE) AS preco_inicio, CAST(f.p_fim AS DOUBLE) AS preco_fim,
       CAST(coalesce(d.div, 0) AS DOUBLE) AS proventos,
       try_divide(CAST(f.p_fim AS DOUBLE) + CAST(coalesce(d.div, 0) AS DOUBLE), CAST(i.p_ini AS DOUBLE)) - 1 AS ret
FROM h
LEFT JOIN fim f ON f.data_ref = h.data_ref AND f.ticker = h.ticker
LEFT JOIN ini i ON i.data_ref = h.data_ref AND i.ticker = h.ticker
LEFT JOIN div d ON d.data_ref = h.data_ref AND d.ticker = h.ticker;
