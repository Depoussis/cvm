-- Dividendos anuais e dividend yield (página Bolsa do painel e variáveis do modelo).

CREATE OR REPLACE VIEW ${catalog}.gold.vw_b3_dividendos_anuais
COMMENT 'Proventos por ticker e ano (data com): soma por ação ajustada a desdobramentos e DY do ano (soma dos yields de cada evento)'
AS
SELECT ticker, year(data_com) AS ano, count(*) AS eventos,
       sum(valor_ajustado) AS valor_ajustado_ano,
       sum(CASE WHEN tipo_provento LIKE 'JRS%' THEN valor_ajustado ELSE 0 END) AS jcp_ajustado_ano,
       sum(yield_evento) AS dy_ano
FROM ${catalog}.gold.fct_provento
GROUP BY ticker, year(data_com);

CREATE OR REPLACE VIEW ${catalog}.gold.vw_b3_dy_12m
COMMENT 'Dividend yield dos últimos 12 meses por ticker: soma dos yields dos eventos com data com nos 12 meses'
AS
SELECT ticker, sum(yield_evento) AS dy_12m, count(*) AS eventos_12m, max(data_com) AS ultima_data_com
FROM ${catalog}.gold.fct_provento
WHERE data_com > add_months(current_date(), -12) AND data_com <= current_date()
GROUP BY ticker;
