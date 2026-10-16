-- Indicadores analíticos (Fase 6). Cruzam CVM (fundos) e BCB (Selic, PTAX).

-- Fundos vs Selic: em cada mês e classificação, a rentabilidade mediana e a percentagem de fundos acima da Selic
-- acumulada no mês (série SGS 4390, em % ao mês). Critérios, para evitar distorções de fundos pequenos ou dados
-- anómalos: só classes (sem subclasse), PL de fim de mês >= R$ 10 milhões, informes em pelo menos 10 dias do mês e
-- |rentabilidade| < 50 % no mês.
CREATE OR REPLACE VIEW ${catalog}.gold.vw_fundos_vs_selic
COMMENT 'Rentabilidade mensal dos fundos (mediana) e % de fundos acima da Selic do mês, por classificação'
AS
WITH base AS (
  SELECT m.mes, coalesce(d.classificacao, d.tipo_classe, 'Sem classificação') AS classificacao,
         m.rentab_mes * 100 AS rentab_pct
  FROM ${catalog}.gold.fct_fundo_mensal m
  LEFT JOIN ${catalog}.gold.dim_fundo_classe d USING (cnpj_classe)
  WHERE m.id_subclasse = '' AND m.pl_fim_mes >= 10000000 AND m.dias_informados >= 10
    AND m.rentab_mes IS NOT NULL AND abs(m.rentab_mes) < 0.5
),
selic AS (
  SELECT data_referencia AS mes, CAST(valor AS DOUBLE) AS selic_mes_pct
  FROM ${catalog}.gold.fct_serie_valor WHERE serie_codigo = 4390
)
SELECT b.mes, b.classificacao, count(*) AS fundos,
       round(percentile_approx(b.rentab_pct, 0.5), 4) AS rentab_mediana_pct,
       s.selic_mes_pct,
       round(100 * avg(CASE WHEN b.rentab_pct > s.selic_mes_pct THEN 1 ELSE 0 END), 1) AS pct_acima_selic
FROM base b JOIN selic s USING (mes)
GROUP BY b.mes, b.classificacao, s.selic_mes_pct;

-- Câmbio mensal: média e fim de mês da PTAX de venda, e variação face ao mês anterior.
CREATE OR REPLACE VIEW ${catalog}.gold.vw_cambio_mensal
COMMENT 'PTAX de venda por moeda e mês: média, fim de mês e variação mensal (%)'
AS
WITH m AS (
  SELECT simbolo, date_trunc('MONTH', data_cotacao) AS mes, avg(cotacao_venda) AS media_venda,
         max_by(cotacao_venda, data_cotacao) AS fim_mes_venda, count(*) AS dias
  FROM ${catalog}.gold.fct_ptax_diario GROUP BY ALL
)
SELECT simbolo, CAST(mes AS DATE) AS mes, round(media_venda, 4) AS media_venda, fim_mes_venda, dias,
       round(100 * (fim_mes_venda / lag(fim_mes_venda) OVER (PARTITION BY simbolo ORDER BY mes) - 1), 2) AS variacao_pct
FROM m;

-- Fundos por mês: PL, cotistas e captação líquida SOMADOS (só classes, sem subclasses).
-- Atenção: fundos de cotas (FIC) aplicam noutros fundos, por isso a soma tem dupla contagem e não é o PL da indústria.
CREATE OR REPLACE VIEW ${catalog}.gold.vw_industria_fundos_mensal
COMMENT 'Somas mensais de PL, cotistas e captação líquida das classes (com dupla contagem de FIC)'
AS
SELECT mes, count(*) AS fundos, round(sum(pl_fim_mes) / 1e9, 2) AS pl_total_bi,
       sum(cotistas_fim_mes) AS cotistas, round(sum(captacao_mes - resgate_mes) / 1e9, 2) AS captacao_liquida_bi
FROM ${catalog}.gold.fct_fundo_mensal
WHERE id_subclasse = ''
GROUP BY mes;

-- Qualidade e operação, para o painel.
CREATE OR REPLACE VIEW ${catalog}.gold.vw_qualidade_resumo
COMMENT 'Resultados das regras de qualidade por dia, regra e severidade'
AS
SELECT date(executed_at) AS dia, table_name, rule_name, severity, result,
       count(*) AS avaliacoes, sum(records_failed) AS registos_falhados, max(executed_at) AS ultima
FROM ${catalog}.control.data_quality_results
GROUP BY ALL;

CREATE OR REPLACE VIEW ${catalog}.gold.vw_execucoes_resumo
COMMENT 'Execuções por dia, pipeline e estado, com duração e volumes'
AS
SELECT date(start_timestamp) AS dia, pipeline_name, layer, execution_status, count(*) AS execucoes,
       sum(records_read) AS lidos, sum(coalesce(records_inserted, 0) + coalesce(records_updated, 0)) AS escritos,
       sum(records_rejected) AS rejeitados,
       round(avg(unix_timestamp(end_timestamp) - unix_timestamp(start_timestamp)), 1) AS duracao_media_s
FROM ${catalog}.control.pipeline_execution
GROUP BY ALL;
