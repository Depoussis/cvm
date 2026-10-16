-- Facto diário de fundos. Carga por substituição do intervalo afetado (INSERT ... REPLACE WHERE).

CREATE TABLE IF NOT EXISTS ${catalog}.gold.fct_fundo_diario (
  cnpj_classe       STRING          NOT NULL,
  id_subclasse      STRING          NOT NULL,
  data_key          INT             NOT NULL,
  dt_comptc         DATE            NOT NULL,
  vl_quota          DECIMAL(27, 12),
  vl_patrim_liq     DECIMAL(17, 2),
  captc_dia         DECIMAL(17, 2),
  resg_dia          DECIMAL(17, 2),
  captacao_liquida  DECIMAL(18, 2)  COMMENT 'captc_dia - resg_dia',
  nr_cotst          INT,
  rentab_dia        DOUBLE          COMMENT 'vl_quota / cota do informe anterior - 1 (NULL no primeiro dia ou cota anterior <= 0)',
  CONSTRAINT pk_fct_fundo_diario PRIMARY KEY (cnpj_classe, id_subclasse, data_key) NOT ENFORCED,
  CONSTRAINT fk_fct_fundo_data FOREIGN KEY (data_key) REFERENCES ${catalog}.gold.dim_data NOT ENFORCED
)
USING DELTA
CLUSTER BY (dt_comptc, cnpj_classe)
COMMENT 'Informe diário dos fundos com captação líquida e rentabilidade diária da cota';
