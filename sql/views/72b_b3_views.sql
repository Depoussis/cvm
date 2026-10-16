-- Desempenho dos papéis da B3 (página "Ações" do painel). Retornos de preço ajustados a desdobramentos e
-- grupamentos detetados (ver gold.fct_cotacao_diaria); não incluem dividendos.

CREATE OR REPLACE VIEW ${catalog}.gold.vw_b3_desempenho
COMMENT 'Papéis com negócios nos últimos 10 dias: último fecho, retornos (dia, mês, ano, 12 meses), liquidez, P/VP dos FII e DY 12 meses das ações'
AS
WITH ult AS (SELECT max(data_pregao) AS d FROM ${catalog}.gold.fct_cotacao_diaria),
f AS (
  SELECT c.*, u.d FROM ${catalog}.gold.fct_cotacao_diaria c CROSS JOIN ult u
  WHERE c.data_pregao >= add_months(u.d, -13)
),
pregoes AS (SELECT count(DISTINCT data_pregao) AS n FROM f WHERE data_pregao > date_sub(d, 30)),
r AS (
  SELECT ticker, max(d) AS data_referencia, max(data_pregao) AS ultimo_negocio,
         max_by(preco_fechamento, data_pregao) AS fechamento,
         max_by(retorno_dia, data_pregao) AS retorno_ultimo,
         max_by(preco_ajustado, data_pregao) AS aj_ult,
         max_by(preco_ajustado, data_pregao) FILTER (WHERE data_pregao <= add_months(d, -1)) AS aj_1m,
         max_by(preco_ajustado, data_pregao) FILTER (WHERE data_pregao < trunc(d, 'YEAR')) AS aj_ano,
         max_by(preco_ajustado, data_pregao) FILTER (WHERE data_pregao <= add_months(d, -12)) AS aj_12m,
         sum(volume) FILTER (WHERE data_pregao > date_sub(d, 30)) AS volume_30d,
         sum(negocios) FILTER (WHERE data_pregao > date_sub(d, 30)) AS negocios_30d
  FROM f GROUP BY ticker
),
fii AS (
  SELECT cnpj_classe, max_by(valor_patrimonial_cota, data_referencia) AS vpc, max(data_referencia) AS mes_vpc
  FROM ${catalog}.silver.cvm_fii_mensal
  WHERE data_referencia >= add_months(trunc(current_date(), 'MM'), -4) AND valor_patrimonial_cota > 0
  GROUP BY cnpj_classe
)
SELECT r.ticker, a.classe_ativo, a.nome_pregao, a.especificacao, a.nome_emissor, a.cnpj_emissor,
       coalesce(a.setor, 'Não informado') AS setor, a.segmento_listagem, a.tipo_papel,
       r.data_referencia, r.ultimo_negocio, r.fechamento,
       CASE WHEN r.ultimo_negocio = r.data_referencia THEN r.retorno_ultimo END AS retorno_dia,
       r.aj_ult / r.aj_1m - 1 AS retorno_1m,
       r.aj_ult / r.aj_ano - 1 AS retorno_ano,
       r.aj_ult / r.aj_12m - 1 AS retorno_12m,
       CAST(coalesce(r.volume_30d, 0) / p.n AS DECIMAL(20, 2)) AS volume_medio_diario,
       CAST(coalesce(r.negocios_30d, 0) / p.n AS DOUBLE) AS negocios_medio_diario,
       CASE WHEN a.classe_ativo = 'FII' THEN CAST(r.fechamento / fii.vpc AS DOUBLE) END AS p_vp,
       fii.mes_vpc,
       dy.dy_12m
FROM r CROSS JOIN pregoes p
JOIN ${catalog}.gold.dim_ativo_b3 a USING (ticker)
LEFT JOIN fii ON a.classe_ativo = 'FII' AND fii.cnpj_classe = a.cnpj_emissor
LEFT JOIN ${catalog}.gold.vw_b3_dy_12m dy ON dy.ticker = r.ticker
WHERE r.ultimo_negocio >= date_sub(r.data_referencia, 10);
