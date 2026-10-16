-- Bronze do Banco Central: registos como recebidos (texto), mais colunas de auditoria. Só recebe INSERTs.
-- Colunas de auditoria comuns:
--   _source_system, _source_entity  origem lógica (bcb_sgs/serie_432, bcb_ptax/cotacao_USD ...)
--   _source_url                     URL exata do pedido
--   _source_file_path               original no volume raw
--   _file_hash                      sha256 do payload
--   _record_hash                    sha256 do registo (deteção de alterações)
--   _request_start, _request_end    intervalo pedido à fonte
--   _ingestion_timestamp, _pipeline_run_id

CREATE TABLE IF NOT EXISTS ${catalog}.bronze.bcb_sgs_valores (
  serie_codigo         INT       NOT NULL,
  data                 STRING    COMMENT 'Texto original dd/MM/aaaa',
  valor                STRING    COMMENT 'Texto original, ponto decimal',
  _source_system       STRING    NOT NULL,
  _source_entity       STRING    NOT NULL,
  _source_url          STRING    NOT NULL,
  _source_file_path    STRING    NOT NULL,
  _file_hash           STRING    NOT NULL,
  _record_hash         STRING    NOT NULL,
  _request_start       DATE,
  _request_end         DATE,
  _ingestion_timestamp TIMESTAMP NOT NULL,
  _pipeline_run_id     STRING    NOT NULL
)
USING DELTA
CLUSTER BY (serie_codigo, _pipeline_run_id)
COMMENT 'SGS/BCB: valores das séries como recebidos da API';

CREATE TABLE IF NOT EXISTS ${catalog}.bronze.bcb_ptax_cotacoes (
  moeda                STRING    NOT NULL,
  paridade_compra      STRING,
  paridade_venda       STRING,
  cotacao_compra       STRING,
  cotacao_venda        STRING,
  data_hora_cotacao    STRING    COMMENT 'Texto original aaaa-MM-dd HH:mm:ss.ffffff (hora de Brasília)',
  tipo_boletim         STRING,
  _source_system       STRING    NOT NULL,
  _source_entity       STRING    NOT NULL,
  _source_url          STRING    NOT NULL,
  _source_file_path    STRING    NOT NULL,
  _file_hash           STRING    NOT NULL,
  _record_hash         STRING    NOT NULL,
  _request_start       DATE,
  _request_end         DATE,
  _ingestion_timestamp TIMESTAMP NOT NULL,
  _pipeline_run_id     STRING    NOT NULL
)
USING DELTA
CLUSTER BY (moeda, _pipeline_run_id)
COMMENT 'PTAX/BCB: boletins de cotação (abertura, intermediários, fechamento) como recebidos';

CREATE TABLE IF NOT EXISTS ${catalog}.bronze.bcb_ptax_moedas (
  simbolo              STRING    NOT NULL,
  nome_formatado       STRING,
  tipo_moeda           STRING,
  _source_system       STRING    NOT NULL,
  _source_entity       STRING    NOT NULL,
  _source_url          STRING    NOT NULL,
  _source_file_path    STRING    NOT NULL,
  _file_hash           STRING    NOT NULL,
  _record_hash         STRING    NOT NULL,
  _request_start       DATE,
  _request_end         DATE,
  _ingestion_timestamp TIMESTAMP NOT NULL,
  _pipeline_run_id     STRING    NOT NULL
)
USING DELTA
COMMENT 'PTAX/BCB: catálogo de moedas como recebido';
