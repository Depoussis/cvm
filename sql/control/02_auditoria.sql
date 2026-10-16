-- Auditoria (Fase 4): reapresentações detetadas e resultados de reconciliação com a fonte.

-- Cada alteração de um valor já publicado numa tabela silver SCD1 (a fonte reviu o dado).
-- Lida do Change Data Feed: par update_preimage/update_postimage da mesma versão Delta.
CREATE TABLE IF NOT EXISTS ${catalog}.control.reapresentacoes (
  table_name          STRING    NOT NULL COMMENT 'Tabela silver (nome UC)',
  chave               STRING    NOT NULL COMMENT 'Chave de negócio em JSON',
  valores_anteriores  STRING    NOT NULL COMMENT 'Colunas de negócio antes da alteração (JSON)',
  valores_novos       STRING    NOT NULL COMMENT 'Colunas de negócio depois da alteração (JSON)',
  colunas_alteradas   ARRAY<STRING> NOT NULL,
  commit_version      BIGINT    NOT NULL,
  commit_timestamp    TIMESTAMP NOT NULL,
  pipeline_run_id     STRING    COMMENT 'Execução que aplicou a alteração',
  detectado_em        TIMESTAMP NOT NULL,
  CONSTRAINT pk_reapresentacoes PRIMARY KEY (table_name, chave, commit_version) NOT ENFORCED
)
USING DELTA
CLUSTER BY (table_name, commit_timestamp)
COMMENT 'Valores revistos pela fonte depois de publicados (SGS, PTAX, informe diário CVM)';

-- Comparação periódica entre a silver e a fonte (contagens e valores).
CREATE TABLE IF NOT EXISTS ${catalog}.control.reconciliation_results (
  reconciliation_id   STRING    NOT NULL,
  pipeline_run_id     STRING    NOT NULL,
  source_system       STRING    NOT NULL,
  entity_name         STRING    NOT NULL,
  periodo             STRING    COMMENT 'Período comparado (ex.: 2026-09, ou intervalo de datas)',
  registos_fonte      BIGINT,
  registos_plataforma BIGINT,
  so_na_fonte         BIGINT    COMMENT 'Chaves que existem na fonte e não na silver',
  so_na_plataforma    BIGINT    COMMENT 'Chaves que existem na silver e não na fonte',
  valores_diferentes  BIGINT    COMMENT 'Chaves comuns com valor diferente',
  resultado           STRING    NOT NULL COMMENT 'OK, DIVERGENTE, FONTE_ATUALIZADA (fonte mudou desde a carga), ERRO',
  detalhe             STRING    COMMENT 'Amostra das divergências (JSON) ou mensagem de erro',
  executed_at         TIMESTAMP NOT NULL,
  CONSTRAINT pk_reconciliation_results PRIMARY KEY (reconciliation_id) NOT ENFORCED
)
USING DELTA
CLUSTER BY (source_system, entity_name)
COMMENT 'Resultados da reconciliação entre a plataforma e as fontes';
