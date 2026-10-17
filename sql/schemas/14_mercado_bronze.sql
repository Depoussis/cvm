-- Bronze das referências de mercado (notebook bronze/mercado; fontes em config/datasets/mercado.yaml).
-- Campos como texto, tal como recebidos (números no formato brasileiro, datas dd/mm/aaaa).

CREATE TABLE IF NOT EXISTS ${catalog}.bronze.b3_indice_dia (
  indice               STRING,
  ano                  STRING,
  mes                  STRING,
  dia                  STRING,
  valor                STRING,
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
COMMENT 'B3: fecho diário dos índices oficiais (IndexCall/GetPortfolioDay), por índice e ano pedidos';

CREATE TABLE IF NOT EXISTS ${catalog}.bronze.tesouro_preco_taxa (
  tipo_titulo          STRING,
  data_vencimento      STRING,
  data_base            STRING,
  taxa_compra          STRING,
  taxa_venda           STRING,
  pu_compra            STRING,
  pu_venda             STRING,
  pu_base              STRING,
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
COMMENT 'Tesouro Direto: preços e taxas por título e data base (Tesouro Transparente); incremental = últimos dias';
