-- Vistas de consumo.

-- Uma linha por dia útil com PTAX de fechamento: juros (SGS) e câmbio (PTAX) lado a lado.
CREATE OR REPLACE VIEW ${catalog}.gold.vw_juros_cambio_diario
COMMENT 'Meta Selic, Selic anualizada e PTAX de venda (USD, EUR) por dia com boletim de fechamento'
AS
SELECT d.data,
       d.ano_mes,
       max(CASE WHEN f.serie_codigo = 432  THEN f.valor END) AS meta_selic,
       max(CASE WHEN f.serie_codigo = 1178 THEN f.valor END) AS selic_anualizada,
       max(CASE WHEN p.simbolo = 'USD' THEN p.cotacao_venda END) AS ptax_usd_venda,
       max(CASE WHEN p.simbolo = 'EUR' THEN p.cotacao_venda END) AS ptax_eur_venda
FROM ${catalog}.gold.dim_data d
JOIN ${catalog}.gold.fct_ptax_diario p ON p.data_key = d.data_key
LEFT JOIN ${catalog}.gold.fct_serie_valor f ON f.data_key = d.data_key AND f.serie_codigo IN (432, 1178)
GROUP BY d.data, d.ano_mes;

-- Último valor publicado de cada série.
CREATE OR REPLACE VIEW ${catalog}.gold.vw_serie_ultimo_valor
COMMENT 'Último valor disponível por série SGS (até hoje)'
AS
SELECT s.serie_codigo, s.nome, s.periodicidade, f.data_referencia, f.valor
FROM ${catalog}.gold.dim_serie s
JOIN (SELECT *, row_number() OVER (PARTITION BY serie_codigo ORDER BY data_referencia DESC) AS rn
      FROM ${catalog}.gold.fct_serie_valor WHERE data_referencia <= current_date()) f
  ON f.serie_codigo = s.serie_codigo AND f.rn = 1;
