"""Cálculo da gold de cotações da B3 (retorno, eventos, preço ajustado), partilhado pelo notebook gold/b3 e pelos
testes de integração (que comparam a carga incremental com uma reconstrução completa)."""
from __future__ import annotations

# tolerância relativa ao comparar preços ajustados calculados por caminhos diferentes (vírgula flutuante)
TOLERANCIA = 1e-9


def calculo(fonte: str, filtro_final: str) -> str:
    """Retorno diário, fator de evento e preço ajustado sobre `fonte` (linhas da silver com a coluna d0).

    O preço ajustado desconta os fatores dos pregões seguintes dentro de `fonte`, por isso `fonte` tem de ir até ao
    último pregão de cada ticker. O primeiro pregão de `fonte` só serve de "fecho anterior" e é cortado por
    `filtro_final`.
    """
    return f"""
WITH b AS (
  SELECT s.*, lag(preco_fechamento) OVER w AS fecho_anterior, lag(distribuicao) OVER w AS distribuicao_anterior
  FROM ({fonte}) s
  WHERE coalesce(especificacao, '') NOT LIKE 'IBO%'   -- IBOV11: cesta do Ibovespa, não é uma ação
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
),
g AS (
  SELECT ticker, data_pregao, CAST(date_format(data_pregao, 'yyyyMMdd') AS INT) AS data_key, classe_ativo,
         preco_abertura, preco_maximo, preco_minimo, preco_fechamento, negocios, quantidade, volume, fator_evento,
         razao / fator_evento - 1 AS retorno_dia,
         CAST(preco_fechamento AS DOUBLE) * coalesce(exp(sum(ln(fator_evento)) OVER (
           PARTITION BY ticker ORDER BY data_pregao ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING)), 1.0)
           AS preco_ajustado,
         d0
  FROM f
)
SELECT * EXCEPT (d0) FROM g WHERE {filtro_final}
"""


def sql_diferencas(fct: str, silver: str) -> str:
    """Linhas em que a tabela gold difere de uma reconstrução completa a partir da silver (deve dar zero)."""
    total = calculo(f"SELECT *, DATE'1900-01-01' AS d0 FROM {silver}", "true")
    return f"""
WITH esperado AS ({total})
SELECT coalesce(e.ticker, t.ticker) AS ticker, coalesce(e.data_pregao, t.data_pregao) AS data_pregao,
       e.preco_ajustado AS esperado, t.preco_ajustado AS obtido
FROM esperado e FULL OUTER JOIN {fct} t ON e.ticker = t.ticker AND e.data_key = t.data_key
WHERE e.ticker IS NULL OR t.ticker IS NULL
   OR NOT (e.fator_evento <=> t.fator_evento)
   OR abs(coalesce(e.retorno_dia, 0) - coalesce(t.retorno_dia, 0)) > {TOLERANCIA}
   OR abs(e.preco_ajustado - t.preco_ajustado) > {TOLERANCIA} * greatest(abs(e.preco_ajustado), 1e-6)  -- há fechos a 0
"""
