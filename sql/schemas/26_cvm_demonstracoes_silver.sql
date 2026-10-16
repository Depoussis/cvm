-- Silver das demonstrações financeiras das companhias abertas (DFP anual e ITR trimestral), notebook silver/cvm.
-- Só o exercício corrente de cada documento (ORDEM_EXERC = 'ÚLTIMO') e a versão mais alta; contas até ao 3.º nível
-- (ex.: 3.11.01). Valores em reais (a CVM publica em milhares: multiplicados por 1000).

CREATE TABLE IF NOT EXISTS ${catalog}.silver.cvm_demo_documento (
  cnpj_cia         STRING    NOT NULL,
  tipo_doc         STRING    NOT NULL COMMENT 'DFP ou ITR',
  dt_refer         DATE      NOT NULL COMMENT 'Fim do período de referência',
  versao           INT       NOT NULL,
  cd_cvm           STRING,
  denom_cia        STRING,
  id_doc           STRING,
  dt_receb         DATE      COMMENT 'Data de entrega à CVM: a partir daqui a informação é pública',
  record_hash      STRING    NOT NULL,
  _inserted_at     TIMESTAMP NOT NULL,
  _updated_at      TIMESTAMP NOT NULL,
  _pipeline_run_id STRING    NOT NULL,
  CONSTRAINT pk_cvm_demo_documento PRIMARY KEY (cnpj_cia, tipo_doc, dt_refer, versao) NOT ENFORCED
)
USING DELTA
COMMENT 'CVM: documentos DFP/ITR entregues (todas as versões), com a data de entrega';

CREATE TABLE IF NOT EXISTS ${catalog}.silver.cvm_demo_conta (
  cnpj_cia         STRING         NOT NULL,
  tipo_doc         STRING         NOT NULL COMMENT 'DFP ou ITR',
  dt_refer         DATE           NOT NULL,
  escopo           STRING         NOT NULL COMMENT 'con (consolidado) ou ind (individual)',
  demonstracao     STRING         NOT NULL COMMENT 'DRE, BPA ou BPP',
  dt_ini_exerc     DATE           NOT NULL COMMENT 'Início do período na DRE; nos balanços (posição numa data) = dt_fim_exerc',
  dt_fim_exerc     DATE           NOT NULL,
  cd_conta         STRING         NOT NULL,
  ds_conta         STRING,
  conta_fixa       STRING         COMMENT 'S = conta padronizada pela CVM',
  valor            DECIMAL(24, 2) COMMENT 'Reais',
  versao           INT            NOT NULL,
  record_hash      STRING         NOT NULL,
  _inserted_at     TIMESTAMP      NOT NULL,
  _updated_at      TIMESTAMP      NOT NULL,
  _pipeline_run_id STRING         NOT NULL,
  CONSTRAINT pk_cvm_demo_conta PRIMARY KEY (cnpj_cia, tipo_doc, dt_refer, escopo, demonstracao, dt_ini_exerc, dt_fim_exerc, cd_conta) NOT ENFORCED
)
USING DELTA
CLUSTER BY (cnpj_cia, dt_refer)
COMMENT 'CVM: contas da DRE e do balanço (DFP/ITR), versão mais alta, até ao 3.º nível (SCD1)';

CREATE TABLE IF NOT EXISTS ${catalog}.silver.cvm_demo_capital (
  cnpj_cia         STRING    NOT NULL,
  tipo_doc         STRING    NOT NULL,
  dt_refer         DATE      NOT NULL,
  versao           INT       NOT NULL,
  acoes_on         BIGINT,
  acoes_pn         BIGINT,
  acoes_total      BIGINT,
  tesouraria_on    BIGINT,
  tesouraria_pn    BIGINT,
  tesouraria_total BIGINT,
  record_hash      STRING    NOT NULL,
  _inserted_at     TIMESTAMP NOT NULL,
  _updated_at      TIMESTAMP NOT NULL,
  _pipeline_run_id STRING    NOT NULL,
  CONSTRAINT pk_cvm_demo_capital PRIMARY KEY (cnpj_cia, tipo_doc, dt_refer) NOT ENFORCED
)
USING DELTA
COMMENT 'CVM: composição do capital (ações integralizadas e em tesouraria) por documento, versão mais alta (SCD1)';
