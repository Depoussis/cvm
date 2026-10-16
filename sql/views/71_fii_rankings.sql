-- Rankings de FII (aba "FII · rankings" do painel). Só dados oficiais da CVM (informe mensal estruturado).
-- Sem cotação de mercado: DY e rentabilidade são os informados à CVM (sobre o PL/cota patrimonial), não sobre o preço.

CREATE OR REPLACE VIEW ${catalog}.gold.vw_fii_ranking
COMMENT 'FII negociados em bolsa com informe nos últimos 4 meses: último mês, PL, cotistas, liquidez, DY e rentabilidade (12 meses)'
AS
WITH m AS (
  SELECT s.*, a.total_necessidades_liquidez, a.disponibilidades,
         year(s.data_referencia) * 12 + month(s.data_referencia) AS mes_n
  FROM ${catalog}.silver.cvm_fii_mensal s
  LEFT JOIN ${catalog}.silver.cvm_fii_ativo_passivo a USING (cnpj_classe, data_referencia)
),
x AS (
  SELECT m.*,
         row_number() OVER (PARTITION BY cnpj_classe ORDER BY data_referencia DESC) AS rn,
         -- janelas de 12 meses de calendário (RANGE sobre o número do mês, não sobre linhas)
         count(*) OVER w12 AS meses_12m,
         sum(CASE WHEN abs(dividend_yield_mes) < 0.5 THEN dividend_yield_mes END) OVER w12 AS dy_12m,
         exp(sum(ln(greatest(1 + rentab_efetiva_mes, 1e-9))) OVER w12) - 1 AS rentab_12m
  FROM m
  WINDOW w12 AS (PARTITION BY cnpj_classe ORDER BY mes_n RANGE BETWEEN 11 PRECEDING AND CURRENT ROW)
)
SELECT cnpj_classe,
       -- ticker derivado do ISIN das cotas (BR + 4 letras do emissor + CTF...): BRKNCRCTF000 → KNCR11
       CASE WHEN codigo_isin RLIKE '^BR[A-Z]{4}CTF' THEN concat(substr(codigo_isin, 3, 4), '11') END AS ticker,
       nome_fundo, coalesce(segmento_atuacao, 'Não informado') AS segmento, nome_administrador,
       data_referencia AS mes, patrimonio_liquido, cotistas, valor_ativo, valor_patrimonial_cota,
       total_necessidades_liquidez / nullif(patrimonio_liquido, 0) AS liquidez_sobre_pl,
       CASE WHEN abs(dividend_yield_mes) < 0.5 THEN dividend_yield_mes END AS dy_mes,
       CASE WHEN meses_12m = 12 THEN dy_12m END AS dy_12m,
       CASE WHEN meses_12m = 12 AND abs(rentab_12m) < 5 THEN rentab_12m END AS rentab_12m
FROM x
WHERE rn = 1 AND negociado_bolsa = 'S'
  AND data_referencia >= add_months(trunc(current_date(), 'MM'), -4);

CREATE OR REPLACE VIEW ${catalog}.gold.vw_fii_segmentos
COMMENT 'FII por segmento: quantidade, PL somado, DY mediano (só DY > 0) e quantos informam DY = 0'
AS
-- ~40 % dos FII informam DY = 0 todos os meses (campo por preencher, na prática): a mediana usa só DY > 0.
SELECT segmento, count(*) AS fundos, round(sum(patrimonio_liquido) / 1e9, 2) AS pl_bi,
       round(percentile_approx(CASE WHEN dy_mes > 0 THEN dy_mes END, 0.5) * 100, 3) AS dy_mediano_mes_pct,
       sum(CASE WHEN coalesce(dy_mes, 0) = 0 THEN 1 ELSE 0 END) AS fundos_dy_zero,
       sum(cotistas) AS posicoes_cotistas
FROM ${catalog}.gold.vw_fii_ranking
GROUP BY segmento;
