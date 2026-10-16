-- Dimensões gold. dim_data é gerada uma vez (2000-2035); as outras são reconstruídas pelo notebook gold.

CREATE TABLE IF NOT EXISTS ${catalog}.gold.dim_data (
  data_key        INT     NOT NULL COMMENT 'AAAAMMDD',
  data            DATE    NOT NULL,
  ano             INT     NOT NULL,
  trimestre       INT     NOT NULL,
  mes             INT     NOT NULL,
  dia             INT     NOT NULL,
  dia_semana_iso  INT     NOT NULL COMMENT '1 = segunda ... 7 = domingo',
  fim_de_semana   BOOLEAN NOT NULL,
  ano_mes         STRING  NOT NULL COMMENT 'AAAA-MM',
  CONSTRAINT pk_dim_data PRIMARY KEY (data_key) NOT ENFORCED
)
USING DELTA
COMMENT 'Calendário';

INSERT INTO ${catalog}.gold.dim_data
SELECT CAST(date_format(d, 'yyyyMMdd') AS INT), d, year(d), quarter(d), month(d), day(d),
       extract(DAYOFWEEK_ISO FROM d), extract(DAYOFWEEK_ISO FROM d) >= 6, date_format(d, 'yyyy-MM')
FROM (SELECT explode(sequence(DATE'2000-01-01', DATE'2035-12-31', INTERVAL 1 DAY)) AS d)
WHERE NOT EXISTS (SELECT 1 FROM ${catalog}.gold.dim_data);

CREATE TABLE IF NOT EXISTS ${catalog}.gold.dim_serie (
  serie_codigo   INT    NOT NULL,
  nome           STRING NOT NULL,
  responsavel    STRING,
  periodicidade  STRING NOT NULL,
  dataset_bcb    STRING,
  CONSTRAINT pk_dim_serie PRIMARY KEY (serie_codigo) NOT ENFORCED
)
USING DELTA
COMMENT 'Séries SGS (versão atual do cadastro)';

CREATE TABLE IF NOT EXISTS ${catalog}.gold.dim_moeda (
  simbolo        STRING NOT NULL,
  nome           STRING NOT NULL,
  tipo_moeda     STRING NOT NULL,
  CONSTRAINT pk_dim_moeda PRIMARY KEY (simbolo) NOT ENFORCED
)
USING DELTA
COMMENT 'Moedas PTAX (versão atual do cadastro)';
