"""Cálculo da gold de cotações da B3 (retorno, preço ajustado), partilhado pelo notebook gold/b3 e pelos testes de
integração (que comparam a carga incremental com uma reconstrução completa).

O fator de evento de cada pregão vem de `gold.fct_evento_acao` (src/gold/eventos.py, o único sítio com as regras de
desdobramentos, grupamentos e bonificações); aqui só se aplica: retorno do dia sem o efeito do evento e preço
ajustado aos eventos posteriores.
"""
from __future__ import annotations

from src.gold.eventos import TABELA as TABELA_EVENTOS

# tolerância relativa ao comparar preços ajustados calculados por caminhos diferentes (vírgula flutuante)
TOLERANCIA = 1e-9


def calculo(k: str, fonte: str, filtro_final: str) -> str:
    """Retorno diário e preço ajustado (fator de `gold.fct_evento_acao`) sobre `fonte` (silver com a coluna d0).

    O preço ajustado desconta os fatores dos pregões seguintes dentro de `fonte`, por isso `fonte` tem de ir até ao
    último pregão de cada ticker. O primeiro pregão de `fonte` só serve de "fecho anterior" e é cortado por
    `filtro_final`.
    """
    return f"""
WITH b AS (
  SELECT s.*, lag(preco_fechamento) OVER w AS fecho_anterior
  FROM ({fonte}) s
  WHERE coalesce(especificacao, '') NOT LIKE 'IBO%'   -- IBOV11: cesta do Ibovespa, não é uma ação
  WINDOW w AS (PARTITION BY ticker ORDER BY data_pregao)
),
f AS (
  SELECT b.*, coalesce(e.fator, 1.0) AS fator_evento,
         CASE WHEN fecho_anterior > 0 AND preco_fechamento > 0
              THEN CAST(preco_fechamento AS DOUBLE) / CAST(fecho_anterior AS DOUBLE) END AS razao
  FROM b LEFT JOIN {k}.{TABELA_EVENTOS} e ON e.ticker = b.ticker AND e.data_ex = b.data_pregao
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


def sql_diferencas(k: str) -> str:
    """Linhas em que a gold difere de uma reconstrução completa a partir da silver (deve dar zero)."""
    total = calculo(k, f"SELECT *, DATE'1900-01-01' AS d0 FROM {k}.silver.b3_cotacao_diaria", "true")
    return f"""
WITH esperado AS ({total})
SELECT coalesce(e.ticker, t.ticker) AS ticker, coalesce(e.data_pregao, t.data_pregao) AS data_pregao,
       e.preco_ajustado AS esperado, t.preco_ajustado AS obtido
FROM esperado e FULL OUTER JOIN {k}.gold.fct_cotacao_diaria t ON e.ticker = t.ticker AND e.data_key = t.data_key
WHERE e.ticker IS NULL OR t.ticker IS NULL
   OR abs(e.fator_evento - t.fator_evento) > {TOLERANCIA} * e.fator_evento
   OR abs(coalesce(e.retorno_dia, 0) - coalesce(t.retorno_dia, 0)) > {TOLERANCIA}
   OR abs(e.preco_ajustado - t.preco_ajustado) > {TOLERANCIA} * greatest(abs(e.preco_ajustado), 1e-6)  -- há fechos a 0
"""
