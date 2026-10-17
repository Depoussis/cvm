-- Silver das referências de mercado (notebook silver/mercado), SCD1.

CREATE TABLE IF NOT EXISTS ${catalog}.silver.b3_indice_diario (
  indice            STRING        NOT NULL COMMENT 'Código B3 (IBOV, IFIX, SMLL, IDIV)',
  data_pregao       DATE          NOT NULL,
  fechamento        DECIMAL(18, 2) NOT NULL COMMENT 'Pontos do índice no fecho',
  record_hash       STRING        NOT NULL,
  _pipeline_run_id  STRING        NOT NULL,
  _inserted_at      TIMESTAMP      NOT NULL,
  _updated_at       TIMESTAMP      NOT NULL,
  CONSTRAINT pk_b3_indice_diario PRIMARY KEY (indice, data_pregao) NOT ENFORCED
)
USING DELTA
CLUSTER BY (indice, data_pregao)
COMMENT 'B3: fecho diário dos índices oficiais (SCD1)';

CREATE TABLE IF NOT EXISTS ${catalog}.silver.tesouro_preco_taxa (
  tipo_titulo       STRING         NOT NULL COMMENT 'Ex.: Tesouro IPCA+, Tesouro Selic, Tesouro Prefixado',
  data_vencimento   DATE           NOT NULL,
  data_base         DATE           NOT NULL COMMENT 'Dia a que os preços e taxas se referem',
  taxa_compra       DECIMAL(9, 4)  COMMENT '% ao ano (sobre o IPCA nos IPCA+, sobre a Selic no Tesouro Selic)',
  taxa_venda        DECIMAL(9, 4),
  pu_compra         DECIMAL(18, 2) COMMENT 'Preço unitário de compra (R$)',
  pu_venda          DECIMAL(18, 2) COMMENT 'Preço unitário de venda antecipada (R$)',
  pu_base           DECIMAL(18, 2),
  record_hash       STRING         NOT NULL,
  _pipeline_run_id  STRING         NOT NULL,
  _inserted_at      TIMESTAMP      NOT NULL,
  _updated_at       TIMESTAMP      NOT NULL,
  CONSTRAINT pk_tesouro_preco_taxa PRIMARY KEY (tipo_titulo, data_vencimento, data_base) NOT ENFORCED
)
USING DELTA
CLUSTER BY (data_base, tipo_titulo)
COMMENT 'Tesouro Direto: preços e taxas diários por título (SCD1)';
