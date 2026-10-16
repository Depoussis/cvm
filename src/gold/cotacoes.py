"""Cálculo da gold de cotações da B3 (retorno, eventos, preço ajustado), partilhado pelo notebook gold/b3 e pelos
testes de integração (que comparam a carga incremental com uma reconstrução completa).

Fator de evento de cada pregão (preço depois = preço antes x fator, sem variação de mercado):
- **Ações de emissores com eventos oficiais da B3** (`silver.b3_evento_acao`, ligados ao ticker pelo ISIN):
  desdobramento f % → 1 / (1 + f/100); bonificação f % → 1 / (1 + f/100); grupamento f (fração) → 1 / f. Vários
  eventos com a mesma data ex multiplicam-se (ex.: desdobramento 9900 % + grupamento 0,01 = 1). Data ex = primeiro
  pregão do papel depois da data com.
- **Restantes papéis (FII, ETF, ações sem dados oficiais):** heurística sobre a própria série (variação do fecho perto
  de um fator inteiro no pregão em que muda o número de distribuição).
"""
from __future__ import annotations

# tolerância relativa ao comparar preços ajustados calculados por caminhos diferentes (vírgula flutuante)
TOLERANCIA = 1e-9
EVENTOS_OFICIAIS = ("DESDOBRAMENTO", "GRUPAMENTO", "BONIFICACAO")


def sql_fator_oficial(k: str) -> str:
    """Fator de preço de cada evento oficial, por ticker e data com."""
    tipos = ", ".join(f"'{t}'" for t in EVENTOS_OFICIAIS)
    return f"""
SELECT a.ticker, o.data_com,
       exp(sum(ln(CASE WHEN o.tipo_evento = 'GRUPAMENTO' THEN 1.0 / CAST(o.fator AS DOUBLE)
                       ELSE 1.0 / (1.0 + CAST(o.fator AS DOUBLE) / 100.0) END))) AS fator_oficial
FROM {k}.silver.b3_evento_acao o
JOIN {k}.gold.dim_ativo_b3 a ON a.isin = o.isin
WHERE o.tipo_evento IN ({tipos}) AND o.fator > 0
GROUP BY a.ticker, o.data_com"""


def sql_cobertura_oficial(k: str) -> str:
    """Tickers cujos eventos vêm da B3: ações de emissores presentes na carga de proventos."""
    return f"""
SELECT a.ticker FROM {k}.gold.dim_ativo_b3 a
WHERE a.classe_ativo = 'Ação' AND substr(a.ticker, 1, 4) IN (SELECT emissor FROM {k}.silver.b3_empresa)"""


def calculo(k: str, fonte: str, filtro_final: str) -> str:
    """Retorno diário, fator de evento e preço ajustado sobre `fonte` (linhas da silver com a coluna d0).

    O preço ajustado desconta os fatores dos pregões seguintes dentro de `fonte`, por isso `fonte` tem de ir até ao
    último pregão de cada ticker. O primeiro pregão de `fonte` só serve de "fecho anterior" e é cortado por
    `filtro_final`.
    """
    return f"""
WITH b AS (
  SELECT s.*, lag(preco_fechamento) OVER w AS fecho_anterior, lag(distribuicao) OVER w AS distribuicao_anterior,
         lag(data_pregao) OVER w AS pregao_anterior
  FROM ({fonte}) s
  WHERE coalesce(especificacao, '') NOT LIKE 'IBO%'   -- IBOV11: cesta do Ibovespa, não é uma ação
  WINDOW w AS (PARTITION BY ticker ORDER BY data_pregao)
),
oficial AS ({sql_fator_oficial(k)}),
cobertura AS ({sql_cobertura_oficial(k)}),
ex AS (           -- evento oficial → pregão em que entra (primeiro depois da data com)
  SELECT b.ticker, b.data_pregao, exp(sum(ln(o.fator_oficial))) AS fator_oficial
  FROM b JOIN oficial o ON o.ticker = b.ticker AND o.data_com >= b.pregao_anterior AND o.data_com < b.data_pregao
  GROUP BY b.ticker, b.data_pregao
),
r AS (
  SELECT b.*, ex.fator_oficial, cob.ticker IS NOT NULL AS tem_oficial,
         CASE WHEN fecho_anterior > 0 AND preco_fechamento > 0
              THEN CAST(preco_fechamento AS DOUBLE) / CAST(fecho_anterior AS DOUBLE) END AS razao
  FROM b
  LEFT JOIN ex ON ex.ticker = b.ticker AND ex.data_pregao = b.data_pregao
  LEFT JOIN cobertura cob ON cob.ticker = b.ticker
),
cand AS (
  -- heurística: fator inteiro mais próximo, 1/k para desdobramentos (preço cai k vezes), k para grupamentos
  SELECT r.*, CASE WHEN razao < 0.6 THEN 1.0 / round(1.0 / razao)
                   WHEN razao > 1.6 THEN round(razao) END AS candidato
  FROM r
),
f AS (
  SELECT cand.*,
         CASE WHEN fator_oficial IS NOT NULL THEN fator_oficial
              WHEN tem_oficial THEN 1.0
              WHEN candidato BETWEEN 0.001 AND 1000 AND distribuicao <> distribuicao_anterior
                   AND abs(razao / candidato - 1) <= 0.08 THEN CAST(candidato AS DOUBLE)
              ELSE 1.0 END AS fator_evento
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
