-- Vistas de consumo da CVM.

CREATE OR REPLACE VIEW ${catalog}.gold.vw_fundos_captacao_mensal
COMMENT 'Captação, resgate e captação líquida mensais por classificação (informes ao nível da classe)'
AS
SELECT date_format(f.dt_comptc, 'yyyy-MM') AS ano_mes,
       coalesce(d.classificacao, d.tipo_classe, 'Sem classificação') AS classificacao,
       count(DISTINCT f.cnpj_classe) AS fundos,
       sum(f.captc_dia) AS captacao,
       sum(f.resg_dia) AS resgate,
       sum(f.captacao_liquida) AS captacao_liquida
FROM ${catalog}.gold.fct_fundo_diario f
LEFT JOIN ${catalog}.gold.dim_fundo_classe d ON d.cnpj_classe = f.cnpj_classe
WHERE f.id_subclasse = ''
GROUP BY 1, 2;

CREATE OR REPLACE VIEW ${catalog}.gold.vw_fundos_maiores_pl
COMMENT 'Fundos/classes por património líquido no último informe de cada um (últimos 10 dias)'
AS
WITH ultimo AS (
  SELECT *, row_number() OVER (PARTITION BY cnpj_classe ORDER BY dt_comptc DESC) AS rn
  FROM ${catalog}.gold.fct_fundo_diario
  WHERE id_subclasse = '' AND dt_comptc >= date_sub((SELECT max(dt_comptc) FROM ${catalog}.gold.fct_fundo_diario), 10)
)
SELECT u.cnpj_classe, d.denominacao_social, d.classificacao, d.administrador, u.dt_comptc,
       u.vl_patrim_liq, u.nr_cotst, rank() OVER (ORDER BY u.vl_patrim_liq DESC) AS posicao
FROM ultimo u
LEFT JOIN ${catalog}.gold.dim_fundo_classe d ON d.cnpj_classe = u.cnpj_classe
WHERE u.rn = 1;
