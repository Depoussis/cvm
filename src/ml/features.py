"""Variáveis (features) e alvo do modelo de ranking de ações, em SQL sobre a gold. Partilhado pelo notebook
ml/features e pelos testes.

Regras para não olhar para o futuro (point-in-time):
- preços: só pregões até à data de referência t (preço ajustado a desdobramentos, comparável no tempo);
- dividendos: só os com data ex até t;
- fundamentos: só demonstrações com data de entrega à CVM até t (não o fim do trimestre);
- alvo: retorno total (preço + dividendos) nos 21 pregões depois de t, acima da mediana das ações nessa data.

Datas de referência: último pregão de cada mês, mais o último pregão disponível (para o ranking atual, sem alvo).
Universo: ações (lote padrão) com volume médio ≥ R$ 1 mi nos 21 pregões até t e pelo menos 252 pregões de histórico.

Valor de mercado = preço ajustado em t x número de ações atual da B3. As duas grandezas estão na base de ações de hoje
(desdobramentos e bonificações já descontados), por isso o produto é o valor de mercado em t, sem depender do número de
ações declarado à CVM (que algumas empresas, como o Itaú, enviam em milhares). Recompras e emissões entre t e hoje não
são captadas. Units (ex.: TAEE11) ficam sem valor de mercado: o preço é de um pacote de ações.
"""
from __future__ import annotations

HORIZONTE = 21          # pregões (~1 mês)
VOLUME_MINIMO = 1_000_000

# Colunas usadas pelo modelo (o resto é identificação, alvo ou diagnóstico)
FEATURES_ACAO = ["ret_1m", "ret_3m", "ret_6m", "mom_12_1", "vol_3m", "log_volume", "dist_max_52s", "dy_12m",
                 "earnings_yield", "book_to_market", "roe", "margem_liquida", "divida_liquida_pl", "log_valor_mercado"]
FEATURES_MACRO = ["selic_meta", "selic_var_3m", "usd_ret_1m"]

SQL_FEATURES = f"""
WITH cal AS (     -- calendário de pregões do mercado e datas de referência
  SELECT DISTINCT data_pregao FROM {{k}}.gold.fct_cotacao_diaria WHERE classe_ativo = 'Ação'
),
refs AS (
  SELECT max(data_pregao) AS data_ref FROM cal GROUP BY date_trunc('MONTH', data_pregao)
  UNION SELECT max(data_pregao) FROM cal
),
d AS (            -- série diária das ações com janelas por número de pregões do próprio papel
  SELECT c.ticker, c.data_pregao, c.preco_fechamento, c.preco_ajustado, c.retorno_dia, c.volume,
         lag(c.preco_ajustado, 21) OVER w AS p21, lag(c.preco_ajustado, 63) OVER w AS p63,
         lag(c.preco_ajustado, 126) OVER w AS p126, lag(c.preco_ajustado, 252) OVER w AS p252,
         lead(c.preco_ajustado, {HORIZONTE}) OVER w AS p_fwd, lead(c.data_pregao, {HORIZONTE}) OVER w AS data_fwd,
         stddev(c.retorno_dia) OVER (PARTITION BY c.ticker ORDER BY c.data_pregao ROWS BETWEEN 62 PRECEDING AND CURRENT ROW) * sqrt(252) AS vol_3m,
         avg(CAST(c.volume AS DOUBLE)) OVER (PARTITION BY c.ticker ORDER BY c.data_pregao ROWS BETWEEN 20 PRECEDING AND CURRENT ROW) AS volume_21d,
         max(c.preco_ajustado) OVER (PARTITION BY c.ticker ORDER BY c.data_pregao ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS max_52s,
         row_number() OVER w AS n_pregoes
  FROM {{k}}.gold.fct_cotacao_diaria c
  WHERE c.classe_ativo = 'Ação'
  WINDOW w AS (PARTITION BY c.ticker ORDER BY c.data_pregao)
),
base AS (
  SELECT d.*, r.data_ref FROM d JOIN refs r ON d.data_pregao = r.data_ref
  WHERE d.n_pregoes > 252 AND d.volume_21d >= {VOLUME_MINIMO} AND d.preco_ajustado > 0
),
div AS (          -- dividendos (ajustados à mesma base do preço ajustado) por data ex
  SELECT b.ticker, b.data_ref,
         sum(CASE WHEN p.data_ex > add_months(b.data_ref, -12) AND p.data_ex <= b.data_ref THEN p.valor_ajustado END)
           AS div_12m,
         sum(CASE WHEN p.data_ex > b.data_ref AND p.data_ex <= b.data_fwd THEN p.valor_ajustado END) AS div_fwd
  FROM base b JOIN {{k}}.gold.fct_provento p ON p.ticker = b.ticker
  GROUP BY 1, 2
),
emissor AS (SELECT ticker, cnpj_emissor, setor FROM {{k}}.gold.dim_ativo_b3),
fund AS (         -- último trimestre publicado até t (no máximo 15 meses antes)
  SELECT b.ticker, b.data_ref, f.*
  FROM base b JOIN emissor e ON e.ticker = b.ticker
  JOIN {{k}}.gold.fct_fundamentos_trimestre f
    ON f.cnpj_cia = e.cnpj_emissor AND f.data_publicacao <= b.data_ref AND f.dt_fim >= add_months(b.data_ref, -15)
  QUALIFY row_number() OVER (PARTITION BY b.ticker, b.data_ref ORDER BY f.dt_fim DESC, f.data_publicacao DESC) = 1
),
acoes AS (       -- nº de ações oficial da B3 (base de hoje, a mesma do preço ajustado); units ficam de fora
  SELECT a.ticker, CAST(e.qtd_acoes_total AS DOUBLE) AS qtd
  FROM {{k}}.gold.dim_ativo_b3 a JOIN {{k}}.silver.b3_empresa e ON e.emissor = substr(a.ticker, 1, 4)
  WHERE a.classe_ativo = 'Ação' AND coalesce(a.tipo_papel, '') <> 'Unit' AND e.qtd_acoes_total > 0
),
selic AS (SELECT data_referencia AS dia, CAST(valor AS DOUBLE) AS v FROM {{k}}.gold.fct_serie_valor WHERE serie_codigo = 432),
usd AS (SELECT data_cotacao AS dia, CAST(cotacao_venda AS DOUBLE) AS v FROM {{k}}.gold.fct_ptax_diario WHERE simbolo = 'USD'),
macro AS (
  SELECT r.data_ref,
         (SELECT max_by(v, dia) FROM selic WHERE dia <= r.data_ref) AS selic_meta,
         (SELECT max_by(v, dia) FROM selic WHERE dia <= r.data_ref)
           - (SELECT max_by(v, dia) FROM selic WHERE dia <= add_months(r.data_ref, -3)) AS selic_var_3m,
         (SELECT max_by(v, dia) FROM usd WHERE dia <= r.data_ref)
           / nullif((SELECT max_by(v, dia) FROM usd WHERE dia <= add_months(r.data_ref, -1)), 0) - 1 AS usd_ret_1m
  FROM refs r
),
j AS (
  SELECT b.*, e.setor, e.cnpj_emissor, dv.div_12m, dv.div_fwd, m.selic_meta, m.selic_var_3m, m.usd_ret_1m,
         f.dt_fim AS fundamentos_trimestre, f.data_publicacao AS fundamentos_publicados,
         CAST(f.lucro_12m AS DOUBLE) AS lucro_12m, CAST(f.receita_12m AS DOUBLE) AS receita_12m,
         CAST(f.patrimonio_liquido AS DOUBLE) AS pl, CAST(f.divida_bruta AS DOUBLE) AS divida,
         CAST(f.caixa AS DOUBLE) AS caixa,
         -- valor de mercado: preço ajustado x nº de ações atual (as duas grandezas na base de ações de hoje, por
         -- isso o produto é o valor de mercado na data t; ignora recompras e emissões, não os desdobramentos)
         b.preco_ajustado * ac.qtd AS valor_mercado
  FROM base b
  JOIN emissor e ON e.ticker = b.ticker
  LEFT JOIN div dv ON dv.ticker = b.ticker AND dv.data_ref = b.data_ref
  LEFT JOIN fund f ON f.ticker = b.ticker AND f.data_ref = b.data_ref
  LEFT JOIN acoes ac ON ac.ticker = b.ticker
  LEFT JOIN macro m ON m.data_ref = b.data_ref
)
SELECT ticker, data_ref, setor, cnpj_emissor,
       try_divide(preco_ajustado, p21) - 1 AS ret_1m, try_divide(preco_ajustado, p63) - 1 AS ret_3m,
       try_divide(preco_ajustado, p126) - 1 AS ret_6m, try_divide(p21, p252) - 1 AS mom_12_1,
       vol_3m, ln(volume_21d) AS log_volume, try_divide(preco_ajustado, max_52s) - 1 AS dist_max_52s,
       try_divide(coalesce(div_12m, 0), preco_ajustado) AS dy_12m,
       valor_mercado,
       try_divide(lucro_12m, valor_mercado) AS earnings_yield,
       try_divide(pl, valor_mercado) AS book_to_market,
       CASE WHEN pl > 0 THEN lucro_12m / pl END AS roe,
       CASE WHEN receita_12m > 0 THEN lucro_12m / receita_12m END AS margem_liquida,
       CASE WHEN pl > 0 THEN (divida - coalesce(caixa, 0)) / pl END AS divida_liquida_pl,
       ln(valor_mercado) AS log_valor_mercado,
       selic_meta, selic_var_3m, usd_ret_1m, fundamentos_trimestre, fundamentos_publicados, data_fwd,
       CASE WHEN p_fwd IS NOT NULL THEN try_divide(p_fwd + coalesce(div_fwd, 0), preco_ajustado) - 1 END AS ret_fwd
FROM j
"""
