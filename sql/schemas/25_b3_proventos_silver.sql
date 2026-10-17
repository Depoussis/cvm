-- Silver dos proventos e eventos societários da B3 (notebook silver/b3_proventos), a partir da carga bronze mais
-- recente. Valores por ação na base de ações da data com (sem ajuste a desdobramentos posteriores).

CREATE TABLE IF NOT EXISTS ${catalog}.silver.b3_provento (
  emissor            STRING         NOT NULL COMMENT 'Código de emissor de 4 letras (raiz do ticker)',
  tipo_acao          STRING         NOT NULL COMMENT 'ON, PN, PNA, PNB, UNT, ...',
  tipo_provento      STRING         NOT NULL COMMENT 'DIVIDENDO, JRS CAP PROPRIO, RENDIMENTO, ...',
  data_com           DATE           NOT NULL COMMENT 'Último dia com direito ao provento',
  data_aprovacao     DATE,
  valor_por_acao     DECIMAL(24, 11) NOT NULL,
  parcela            INT            NOT NULL COMMENT 'Linhas iguais na fonte = parcelas do mesmo provento (1, 2, ...)',
  fecho_data_com     DECIMAL(18, 6) COMMENT 'Fecho na data com, segundo a B3',
  provento_pct_preco DOUBLE         COMMENT 'Valor / fecho na data com, em % (segundo a B3)',
  cotacao_por_acoes  INT            COMMENT 'Lote de cotação a que o valor se refere (normalmente 1)',
  nome_pregao        STRING,
  record_hash        STRING         NOT NULL,
  _inserted_at       TIMESTAMP      NOT NULL,
  _updated_at        TIMESTAMP      NOT NULL,
  _pipeline_run_id   STRING         NOT NULL,
  CONSTRAINT pk_b3_provento PRIMARY KEY (emissor, tipo_acao, tipo_provento, data_com, valor_por_acao, parcela) NOT ENFORCED
)
USING DELTA
CLUSTER BY (emissor, data_com)
COMMENT 'B3: dividendos, JCP e rendimentos por ação (SCD1, histórico completo)'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true');

CREATE TABLE IF NOT EXISTS ${catalog}.silver.b3_evento_acao (
  emissor          STRING         NOT NULL,
  isin             STRING         NOT NULL,
  tipo_evento      STRING         NOT NULL COMMENT 'DESDOBRAMENTO, GRUPAMENTO, BONIFICACAO, ...',
  data_com         DATE           NOT NULL,
  data_aprovacao   DATE,
  fator            DECIMAL(24, 11) NOT NULL COMMENT 'Como publicado pela B3 (ex.: 100 num desdobramento 1:100)',
  record_hash      STRING         NOT NULL,
  _inserted_at     TIMESTAMP      NOT NULL,
  _updated_at      TIMESTAMP      NOT NULL,
  _pipeline_run_id STRING         NOT NULL,
  CONSTRAINT pk_b3_evento_acao PRIMARY KEY (emissor, isin, tipo_evento, data_com) NOT ENFORCED
)
USING DELTA
COMMENT 'B3: eventos em ações (desdobramentos, grupamentos, bonificações), oficiais (SCD1)';

CREATE TABLE IF NOT EXISTS ${catalog}.silver.b3_empresa (
  emissor          STRING    NOT NULL,
  cnpj             STRING,
  razao_social     STRING,
  nome_pregao      STRING,
  codigo_cvm       STRING,
  segmento         STRING,
  qtd_acoes_on     BIGINT,
  qtd_acoes_pn     BIGINT,
  qtd_acoes_total  BIGINT,
  data_referencia  DATE      NOT NULL COMMENT 'Data da carga de onde vem o número de ações',
  record_hash      STRING    NOT NULL,
  _inserted_at     TIMESTAMP NOT NULL,
  _updated_at      TIMESTAMP NOT NULL,
  _pipeline_run_id STRING    NOT NULL,
  CONSTRAINT pk_b3_empresa PRIMARY KEY (emissor) NOT ENFORCED
)
USING DELTA
COMMENT 'B3: empresas com ações negociadas, CNPJ e número de ações (SCD1, última carga)';
