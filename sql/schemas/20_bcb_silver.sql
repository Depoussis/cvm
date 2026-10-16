-- Silver do Banco Central: tipado, deduplicado, uma linha por chave de negócio.
-- Factos de valor (séries, cotações) em SCD1: a fonte pode rever valores e guardamos o último.
-- As versões anteriores continuam disponíveis pelo histórico Delta e pela bronze.
-- Cadastros (séries, moedas) em SCD2: cada alteração de nome/periodicidade/tipo cria uma versão nova.

CREATE TABLE IF NOT EXISTS ${catalog}.silver.bcb_sgs_valores (
  serie_codigo     INT            NOT NULL,
  data_referencia  DATE           NOT NULL,
  valor            DECIMAL(24, 8) NOT NULL,
  record_hash      STRING         NOT NULL,
  _inserted_at     TIMESTAMP      NOT NULL,
  _updated_at      TIMESTAMP      NOT NULL,
  _pipeline_run_id STRING         NOT NULL,
  CONSTRAINT pk_bcb_sgs_valores PRIMARY KEY (serie_codigo, data_referencia) NOT ENFORCED
)
USING DELTA
CLUSTER BY (serie_codigo, data_referencia)
COMMENT 'SGS/BCB: valor por série e data de referência (SCD1)'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true');

CREATE TABLE IF NOT EXISTS ${catalog}.silver.bcb_sgs_series (
  serie_codigo     INT       NOT NULL,
  nome             STRING    NOT NULL,
  responsavel      STRING,
  periodicidade    STRING    NOT NULL,
  dataset_bcb      STRING,
  record_hash      STRING    NOT NULL,
  valid_from       TIMESTAMP NOT NULL,
  valid_to         TIMESTAMP,
  is_current       BOOLEAN   NOT NULL,
  _pipeline_run_id STRING    NOT NULL
)
USING DELTA
COMMENT 'SGS/BCB: cadastro das séries carregadas (SCD2, origem config/series/bcb_sgs.yaml)';

CREATE TABLE IF NOT EXISTS ${catalog}.silver.bcb_ptax_cotacoes (
  moeda             STRING         NOT NULL,
  data_hora_cotacao TIMESTAMP      NOT NULL COMMENT 'Hora de Brasília, como publicada',
  data_cotacao      DATE           NOT NULL,
  tipo_boletim      STRING         NOT NULL,
  paridade_compra   DECIMAL(24, 8) NOT NULL,
  paridade_venda    DECIMAL(24, 8) NOT NULL,
  cotacao_compra    DECIMAL(24, 8) NOT NULL,
  cotacao_venda     DECIMAL(24, 8) NOT NULL,
  record_hash       STRING         NOT NULL,
  _inserted_at      TIMESTAMP      NOT NULL,
  _updated_at       TIMESTAMP      NOT NULL,
  _pipeline_run_id  STRING         NOT NULL,
  CONSTRAINT pk_bcb_ptax_cotacoes PRIMARY KEY (moeda, data_hora_cotacao, tipo_boletim) NOT ENFORCED
)
USING DELTA
CLUSTER BY (moeda, data_cotacao)
COMMENT 'PTAX/BCB: cotações por moeda e boletim (SCD1)'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true');

CREATE TABLE IF NOT EXISTS ${catalog}.silver.bcb_ptax_moedas (
  simbolo          STRING    NOT NULL,
  nome_formatado   STRING    NOT NULL,
  tipo_moeda       STRING    NOT NULL COMMENT 'A ou B, como publicado pelo BCB',
  record_hash      STRING    NOT NULL,
  valid_from       TIMESTAMP NOT NULL,
  valid_to         TIMESTAMP,
  is_current       BOOLEAN   NOT NULL,
  _pipeline_run_id STRING    NOT NULL
)
USING DELTA
COMMENT 'PTAX/BCB: moedas (SCD2)';
