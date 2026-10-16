-- Silver dos fundos imobiliários: informe mensal (complemento + geral do mesmo ficheiro), uma linha por
-- (CNPJ, mês) com a versão mais alta enviada pelo administrador. Percentuais da CVM guardados como FRAÇÃO
-- (0,0057 = 0,57 % no mês), tal como publicados.
CREATE TABLE IF NOT EXISTS ${catalog}.silver.cvm_fii_mensal (
  cnpj_classe            STRING          NOT NULL COMMENT 'CNPJ do fundo/classe, 14 dígitos',
  data_referencia        DATE            NOT NULL COMMENT 'Mês de referência (dia 1)',
  versao                 INT             NOT NULL COMMENT 'Versão do informe (reenvios do administrador)',
  data_entrega           DATE,
  tipo_fundo_classe      STRING,
  nome_fundo             STRING,
  segmento_atuacao       STRING,
  mandato                STRING,
  tipo_gestao            STRING,
  publico_alvo           STRING,
  codigo_isin            STRING,
  negociado_bolsa        STRING          COMMENT 'S/N',
  nome_administrador     STRING,
  cnpj_administrador     STRING,
  cotistas               INT,
  valor_ativo            DECIMAL(20, 2),
  patrimonio_liquido     DECIMAL(20, 2),
  cotas_emitidas         DECIMAL(24, 6),
  valor_patrimonial_cota DECIMAL(27, 12),
  taxa_administracao_mes DOUBLE          COMMENT 'Fração do PL',
  rentab_efetiva_mes     DOUBLE          COMMENT 'Fração (rentabilidade efetiva no mês, inclui rendimentos)',
  rentab_patrimonial_mes DOUBLE          COMMENT 'Fração (variação da cota patrimonial)',
  dividend_yield_mes     DOUBLE          COMMENT 'Fração (rendimentos distribuídos / PL)',
  amortizacao_mes        DOUBLE          COMMENT 'Fração',
  record_hash            STRING          NOT NULL,
  _inserted_at           TIMESTAMP       NOT NULL,
  _updated_at            TIMESTAMP       NOT NULL,
  _pipeline_run_id       STRING          NOT NULL,
  CONSTRAINT pk_cvm_fii_mensal PRIMARY KEY (cnpj_classe, data_referencia) NOT ENFORCED
)
USING DELTA
CLUSTER BY (data_referencia, cnpj_classe)
COMMENT 'CVM: informe mensal estruturado dos FII (SCD1, versão mais alta por mês)'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true');
