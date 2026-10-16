-- Bronze da CVM. As tabelas dos CSV (cvm_fi_inf_diario, cvm_fi_registro_*, cvm_cia_aberta_cad) são criadas pelo
-- notebook bronze/cvm a partir do contrato em config/datasets/cvm.yaml, porque as colunas vêm do cabeçalho.
-- Aqui fica só o catálogo de recursos dos pacotes CKAN.

CREATE TABLE IF NOT EXISTS ${catalog}.bronze.cvm_catalogo_recursos (
  pacote               STRING NOT NULL,
  titulo_pacote        STRING,
  pacote_modificado    STRING,
  recurso_id           STRING NOT NULL,
  nome                 STRING,
  formato              STRING,
  url                  STRING NOT NULL,
  recurso_criado       STRING,
  recurso_modificado   STRING,
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
COMMENT 'CVM: recursos (ficheiros) publicados em cada pacote do portal de dados abertos, por execução';
