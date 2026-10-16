-- Factos gold, reconstruídos a partir da silver pelo notebook gold (INSERT OVERWRITE, idempotente).

CREATE TABLE IF NOT EXISTS ${catalog}.gold.fct_serie_valor (
  serie_codigo     INT            NOT NULL,
  data_key         INT            NOT NULL,
  data_referencia  DATE           NOT NULL,
  valor            DECIMAL(24, 8) NOT NULL,
  CONSTRAINT pk_fct_serie_valor PRIMARY KEY (serie_codigo, data_key) NOT ENFORCED,
  CONSTRAINT fk_fct_serie_valor_serie FOREIGN KEY (serie_codigo) REFERENCES ${catalog}.gold.dim_serie NOT ENFORCED,
  CONSTRAINT fk_fct_serie_valor_data FOREIGN KEY (data_key) REFERENCES ${catalog}.gold.dim_data NOT ENFORCED
)
USING DELTA
CLUSTER BY (serie_codigo, data_referencia)
COMMENT 'Valor de cada série SGS por data de referência';

CREATE TABLE IF NOT EXISTS ${catalog}.gold.fct_ptax_diario (
  simbolo          STRING         NOT NULL,
  data_key         INT            NOT NULL,
  data_cotacao     DATE           NOT NULL,
  cotacao_compra   DECIMAL(24, 8) NOT NULL COMMENT 'R$ por unidade da moeda, boletim de fechamento',
  cotacao_venda    DECIMAL(24, 8) NOT NULL,
  paridade_compra  DECIMAL(24, 8) NOT NULL,
  paridade_venda   DECIMAL(24, 8) NOT NULL,
  CONSTRAINT pk_fct_ptax_diario PRIMARY KEY (simbolo, data_key) NOT ENFORCED,
  CONSTRAINT fk_fct_ptax_moeda FOREIGN KEY (simbolo) REFERENCES ${catalog}.gold.dim_moeda NOT ENFORCED,
  CONSTRAINT fk_fct_ptax_data FOREIGN KEY (data_key) REFERENCES ${catalog}.gold.dim_data NOT ENFORCED
)
USING DELTA
CLUSTER BY (simbolo, data_cotacao)
COMMENT 'PTAX de fechamento por moeda e dia';
