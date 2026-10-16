-- Facto mensal dos fundos imobiliários (reconstruído pelo notebook gold/cvm).
CREATE TABLE IF NOT EXISTS ${catalog}.gold.fct_fii_mensal (
  cnpj_classe            STRING          NOT NULL,
  mes                    DATE            NOT NULL,
  data_key               INT             NOT NULL,
  nome_fundo             STRING,
  segmento_atuacao       STRING,
  nome_administrador     STRING,
  cotistas               INT,
  patrimonio_liquido     DECIMAL(20, 2),
  valor_patrimonial_cota DECIMAL(27, 12),
  rentab_efetiva_mes     DOUBLE          COMMENT 'Fração',
  rentab_patrimonial_mes DOUBLE          COMMENT 'Fração',
  dividend_yield_mes     DOUBLE          COMMENT 'Fração',
  versao                 INT,
  CONSTRAINT pk_fct_fii_mensal PRIMARY KEY (cnpj_classe, mes) NOT ENFORCED,
  CONSTRAINT fk_fct_fii_data FOREIGN KEY (data_key) REFERENCES ${catalog}.gold.dim_data NOT ENFORCED
)
USING DELTA
CLUSTER BY (mes, cnpj_classe)
COMMENT 'Fundos imobiliários por mês: PL, cota patrimonial, cotistas, rentabilidade e dividend yield';
