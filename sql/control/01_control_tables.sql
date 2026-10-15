-- Tabelas de controlo e auditoria (Delta, geridas pelo Unity Catalog no schema control).
-- ${catalog} é substituído pelo catálogo do ambiente (findata_dev, findata_test, findata_prod).
-- Idempotente: CREATE TABLE IF NOT EXISTS. Alterações de esquema entram em ficheiros novos (02_..., 03_...).

-- Uma linha por execução de pipeline e entidade. Escrita no início (RUNNING) e atualizada no fim.
CREATE TABLE IF NOT EXISTS ${catalog}.control.pipeline_execution (
  pipeline_run_id      STRING    NOT NULL COMMENT 'ID da execução (ADF RunId ou Databricks job run id)',
  pipeline_name        STRING    NOT NULL,
  source_system        STRING    NOT NULL COMMENT 'bcb_sgs, bcb_ptax, cvm ...',
  entity_name          STRING    NOT NULL COMMENT 'Série, moeda ou conjunto de dados processado',
  layer                STRING    NOT NULL COMMENT 'bronze, silver, gold',
  run_mode             STRING    NOT NULL COMMENT 'backfill, incremental, reprocess, reconciliation',
  start_timestamp      TIMESTAMP NOT NULL,
  end_timestamp        TIMESTAMP,
  execution_status     STRING    NOT NULL COMMENT 'RUNNING, SUCCEEDED, FAILED, SKIPPED',
  records_read         BIGINT,
  records_inserted     BIGINT,
  records_updated      BIGINT,
  records_deleted      BIGINT,
  records_rejected     BIGINT,
  records_unchanged    BIGINT,
  error_code           STRING,
  error_message        STRING,
  retry_count          INT,
  watermark_start      STRING    COMMENT 'Início do intervalo pedido (texto ISO; o tipo depende da entidade)',
  watermark_end        STRING    COMMENT 'Fim do intervalo pedido',
  parameters           STRING    COMMENT 'Parâmetros da execução em JSON',
  updated_at           TIMESTAMP NOT NULL,
  CONSTRAINT pk_pipeline_execution PRIMARY KEY (pipeline_run_id, entity_name, layer) NOT ENFORCED
)
USING DELTA
CLUSTER BY (source_system, entity_name)
COMMENT 'Registo de cada execução de pipeline por entidade e camada'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true');

-- Último ponto confirmado por fonte e entidade. Só é avançado depois de o processamento e as validações
-- críticas terem sucesso (ver src/audit/control.py). review_window_days define quanto reprocessar para trás.
CREATE TABLE IF NOT EXISTS ${catalog}.control.ingestion_watermark (
  source_system        STRING    NOT NULL,
  entity_name          STRING    NOT NULL,
  watermark_type       STRING    NOT NULL COMMENT 'reference_date, file_last_modified, file_hash ...',
  watermark_value      STRING    NOT NULL COMMENT 'Valor ISO do último ponto confirmado',
  review_window_days   INT       COMMENT 'Janela de revisão aplicada na próxima carga incremental',
  last_full_reconciliation TIMESTAMP COMMENT 'Última reconciliação completa com a fonte',
  pipeline_run_id      STRING    NOT NULL COMMENT 'Execução que confirmou o watermark',
  updated_at           TIMESTAMP NOT NULL,
  CONSTRAINT pk_ingestion_watermark PRIMARY KEY (source_system, entity_name) NOT ENFORCED
)
USING DELTA
COMMENT 'Watermark confirmado por fonte e entidade'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true');

-- Resultado de cada regra de qualidade por tabela e execução.
CREATE TABLE IF NOT EXISTS ${catalog}.control.data_quality_results (
  dq_result_id         STRING    NOT NULL,
  pipeline_run_id      STRING    NOT NULL,
  table_name           STRING    NOT NULL COMMENT 'Nome qualificado no Unity Catalog',
  rule_name            STRING    NOT NULL,
  rule_description     STRING,
  severity             STRING    NOT NULL COMMENT 'CRITICAL, HIGH, INFO',
  result               STRING    NOT NULL COMMENT 'PASSED, FAILED, ERROR',
  records_evaluated    BIGINT,
  records_failed       BIGINT,
  failed_sample        STRING    COMMENT 'Amostra (JSON) dos registos inválidos, limitada',
  blocks_publication   BOOLEAN   NOT NULL COMMENT 'true quando a falha impede a publicação Gold',
  executed_at          TIMESTAMP NOT NULL,
  CONSTRAINT pk_data_quality_results PRIMARY KEY (dq_result_id) NOT ENFORCED
)
USING DELTA
CLUSTER BY (table_name, executed_at)
COMMENT 'Resultados das regras de qualidade';

-- Cada ficheiro ou payload recebido. Um mesmo URL pode ter várias versões (hash diferente) ao longo do tempo.
CREATE TABLE IF NOT EXISTS ${catalog}.control.source_file_registry (
  file_id              STRING    NOT NULL COMMENT 'sha256 do conteúdo + caminho de origem',
  source_system        STRING    NOT NULL,
  entity_name          STRING    NOT NULL,
  source_url           STRING    NOT NULL,
  source_file_name     STRING    NOT NULL,
  stored_path          STRING    NOT NULL COMMENT 'Caminho do original no volume raw (nunca sobrescrito)',
  file_hash_sha256     STRING    NOT NULL,
  file_size_bytes      BIGINT    NOT NULL,
  source_last_modified TIMESTAMP COMMENT 'Last-Modified/ETag informado pela fonte',
  source_etag          STRING,
  reference_period     STRING    COMMENT 'Período a que o ficheiro se refere (ex.: 2024-01)',
  received_at          TIMESTAMP NOT NULL,
  pipeline_run_id      STRING    NOT NULL,
  processing_status    STRING    NOT NULL COMMENT 'RECEIVED, DUPLICATE, PROCESSED, QUARANTINED, FAILED',
  status_detail        STRING,
  version_number       INT       NOT NULL COMMENT 'Versão do ficheiro para o mesmo source_url (1, 2, ...)',
  updated_at           TIMESTAMP NOT NULL,
  CONSTRAINT pk_source_file_registry PRIMARY KEY (file_id) NOT ENFORCED
)
USING DELTA
CLUSTER BY (source_system, entity_name)
COMMENT 'Registo de ficheiros e payloads recebidos, com hash e versão'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true');
