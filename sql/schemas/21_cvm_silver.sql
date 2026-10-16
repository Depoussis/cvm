-- Silver da CVM. CNPJ normalizado para 14 dígitos (o informe publica com pontuação, os cadastros sem).
-- Dados pessoais (diretor, CPF de gestor pessoa física, contactos do responsável) não entram aqui
-- (ver dados_pessoais em config/datasets/cvm.yaml).

-- Informe diário (SCD1). id_subclasse = '' quando o informe é da classe (sem subclasse).
CREATE TABLE IF NOT EXISTS ${catalog}.silver.cvm_fi_informe_diario (
  cnpj_classe      STRING          NOT NULL COMMENT 'CNPJ do fundo/classe, 14 dígitos',
  id_subclasse     STRING          NOT NULL COMMENT 'Identificador da subclasse; vazio quando não se aplica',
  dt_comptc        DATE            NOT NULL COMMENT 'Data de competência',
  tp_fundo_classe  STRING,
  vl_total         DECIMAL(17, 2)  COMMENT 'Valor total da carteira',
  vl_quota         DECIMAL(27, 12) COMMENT 'Valor da cota',
  vl_patrim_liq    DECIMAL(17, 2)  COMMENT 'Património líquido',
  captc_dia        DECIMAL(17, 2)  COMMENT 'Captação do dia',
  resg_dia         DECIMAL(17, 2)  COMMENT 'Resgate do dia',
  nr_cotst         INT             COMMENT 'Número de cotistas',
  record_hash      STRING          NOT NULL,
  _inserted_at     TIMESTAMP       NOT NULL,
  _updated_at      TIMESTAMP       NOT NULL,
  _pipeline_run_id STRING          NOT NULL,
  CONSTRAINT pk_cvm_fi_informe_diario PRIMARY KEY (cnpj_classe, id_subclasse, dt_comptc) NOT ENFORCED
)
USING DELTA
CLUSTER BY (dt_comptc, cnpj_classe)
COMMENT 'CVM: informe diário de fundos/classes/subclasses (SCD1; tipos do dicionário de dados da CVM)'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true');

-- Fundos (SCD2). O CSV traz uma linha por gestor; aqui fica uma linha por registo de fundo.
CREATE TABLE IF NOT EXISTS ${catalog}.silver.cvm_fundo (
  id_registro_fundo      STRING    NOT NULL,
  cnpj_fundo             STRING    NOT NULL,
  codigo_cvm             STRING,
  tipo_fundo             STRING,
  denominacao_social     STRING,
  situacao               STRING,
  data_registro          DATE,
  data_constituicao      DATE,
  data_cancelamento      DATE,
  data_inicio_situacao   DATE,
  data_adaptacao_rcvm175 DATE,
  cnpj_administrador     STRING,
  administrador          STRING,
  record_hash            STRING    NOT NULL,
  valid_from             TIMESTAMP NOT NULL,
  valid_to               TIMESTAMP,
  is_current             BOOLEAN   NOT NULL,
  _pipeline_run_id       STRING    NOT NULL
)
USING DELTA
CLUSTER BY (id_registro_fundo)
COMMENT 'CVM: registo de fundos (SCD2)';

-- Gestores pessoa jurídica de cada fundo (SCD2). Gestores pessoa física são excluídos (CPF).
CREATE TABLE IF NOT EXISTS ${catalog}.silver.cvm_fundo_gestor (
  id_registro_fundo STRING    NOT NULL,
  cnpj_gestor       STRING    NOT NULL,
  gestor            STRING,
  record_hash       STRING    NOT NULL,
  valid_from        TIMESTAMP NOT NULL,
  valid_to          TIMESTAMP,
  is_current        BOOLEAN   NOT NULL,
  _pipeline_run_id  STRING    NOT NULL
)
USING DELTA
COMMENT 'CVM: gestores (pessoa jurídica) por fundo (SCD2)';

-- Classes de cotas (SCD2). Custodiantes/controladores múltiplos agregados por ordem alfabética.
CREATE TABLE IF NOT EXISTS ${catalog}.silver.cvm_fundo_classe (
  id_registro_classe   STRING    NOT NULL,
  id_registro_fundo    STRING,
  cnpj_classe          STRING    NOT NULL,
  codigo_cvm           STRING,
  tipo_classe          STRING,
  denominacao_social   STRING,
  situacao             STRING,
  data_registro        DATE,
  data_inicio          DATE,
  data_inicio_situacao DATE,
  classificacao        STRING,
  classificacao_anbima STRING,
  publico_alvo         STRING,
  forma_condominio     STRING,
  exclusivo            STRING,
  cnpj_auditor         STRING,
  auditor              STRING,
  custodiantes         STRING,
  controladores        STRING,
  record_hash          STRING    NOT NULL,
  valid_from           TIMESTAMP NOT NULL,
  valid_to             TIMESTAMP,
  is_current           BOOLEAN   NOT NULL,
  _pipeline_run_id     STRING    NOT NULL
)
USING DELTA
CLUSTER BY (cnpj_classe)
COMMENT 'CVM: classes de cotas dos fundos (SCD2)';

-- Companhias abertas (SCD2). O CSV traz uma linha por mercado (TP_MERC); aqui uma linha por código CVM.
CREATE TABLE IF NOT EXISTS ${catalog}.silver.cvm_companhia (
  cd_cvm             STRING    NOT NULL,
  cnpj_cia           STRING    NOT NULL,
  denom_social       STRING,
  denom_comerc       STRING,
  dt_reg             DATE,
  dt_const           DATE,
  dt_cancel          DATE,
  motivo_cancel      STRING,
  sit                STRING,
  dt_ini_sit         DATE,
  setor_ativ         STRING,
  tp_merc            STRING    COMMENT 'Mercados, separados por " | "',
  categ_reg          STRING,
  sit_emissor        STRING,
  controle_acionario STRING,
  mun                STRING,
  uf                 STRING,
  pais               STRING,
  cnpj_auditor       STRING,
  auditor            STRING,
  record_hash        STRING    NOT NULL,
  valid_from         TIMESTAMP NOT NULL,
  valid_to           TIMESTAMP,
  is_current         BOOLEAN   NOT NULL,
  _pipeline_run_id   STRING    NOT NULL
)
USING DELTA
COMMENT 'CVM: companhias abertas (SCD2)';
