-- Bronze dos proventos da B3 (notebook bronze/b3_proventos). Campos da API como texto, nomes em
-- src/ingestion/b3/proventos.py: CAMPOS. Uma cópia completa por execução semanal (a silver fica com a mais recente).

CREATE TABLE IF NOT EXISTS ${catalog}.bronze.b3_empresas (
  emissor              STRING,
  razao_social         STRING,
  nome_pregao          STRING,
  cnpj                 STRING,
  codigo_cvm           STRING,
  segmento             STRING,
  indicador_mercado    STRING,
  tipo                 STRING,
  situacao             STRING,
  data_listagem        STRING,
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
COMMENT 'B3: lista de empresas listadas (GetInitialCompanies), por execução';

CREATE TABLE IF NOT EXISTS ${catalog}.bronze.b3_empresa_complemento (
  emissor              STRING,
  nome_pregao          STRING,
  codigo               STRING,
  codigo_cvm           STRING,
  qtd_acoes_on         STRING,
  qtd_acoes_pn         STRING,
  qtd_acoes_total      STRING,
  segmento             STRING,
  capital_social       STRING,
  cotacao_por_acao_desde STRING,
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
COMMENT 'B3: número de ações e dados da empresa (GetListedSupplementCompany), por execução';

CREATE TABLE IF NOT EXISTS ${catalog}.bronze.b3_eventos_acoes (
  emissor              STRING,
  ativo_emitido        STRING,
  isin                 STRING,
  fator                STRING,
  data_aprovacao       STRING,
  tipo_evento          STRING,
  data_com             STRING,
  observacoes          STRING,
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
COMMENT 'B3: desdobramentos, grupamentos e bonificações (stockDividends), por execução';

CREATE TABLE IF NOT EXISTS ${catalog}.bronze.b3_proventos_dinheiro (
  emissor              STRING,
  nome_pregao_pedido   STRING,
  tipo_acao            STRING,
  data_aprovacao       STRING,
  valor                STRING,
  proporcao            STRING,
  tipo_provento        STRING,
  data_com             STRING,
  data_fecho_data_com  STRING,
  fecho_data_com       STRING,
  cotacao_por_acoes    STRING,
  provento_pct_preco   STRING,
  data_hora_com        STRING,
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
COMMENT 'B3: dividendos e JCP por ação (GetListedCashDividends), histórico completo, por execução';
