-- Gold das referências de mercado (reconstruída pelo notebook gold/mercado a partir da silver; tabelas pequenas).

CREATE TABLE IF NOT EXISTS ${catalog}.gold.fct_indice_diario (
  indice        STRING         NOT NULL,
  nome_indice   STRING         COMMENT 'Ex.: Ibovespa, Índice de fundos imobiliários',
  data_pregao   DATE           NOT NULL,
  fechamento    DECIMAL(18, 2) NOT NULL,
  retorno_dia   DOUBLE         COMMENT 'Variação face ao pregão anterior do índice',
  CONSTRAINT pk_fct_indice_diario PRIMARY KEY (indice, data_pregao) NOT ENFORCED
)
USING DELTA
CLUSTER BY (indice, data_pregao)
COMMENT 'Índices oficiais da B3 (IBOV, IFIX, SMLL, IDIV): fecho diário. São de retorno total (proventos reinvestidos)';

CREATE TABLE IF NOT EXISTS ${catalog}.gold.fct_tesouro_diario (
  titulo           STRING         NOT NULL COMMENT 'Nome como no site do Tesouro Direto (ex.: Tesouro IPCA+ 2035)',
  tipo_titulo      STRING         NOT NULL,
  indexador        STRING         COMMENT 'IPCA, Selic, Prefixado ou IGP-M',
  juros_semestrais BOOLEAN,
  data_vencimento  DATE           NOT NULL,
  data_base        DATE           NOT NULL,
  taxa_compra      DECIMAL(9, 4),
  taxa_venda       DECIMAL(9, 4),
  pu_compra        DECIMAL(18, 2),
  pu_venda         DECIMAL(18, 2),
  pu_base          DECIMAL(18, 2),
  CONSTRAINT pk_fct_tesouro_diario PRIMARY KEY (tipo_titulo, data_vencimento, data_base) NOT ENFORCED
)
USING DELTA
CLUSTER BY (data_base, tipo_titulo)
COMMENT 'Tesouro Direto: preços e taxas diários por título, com indexador';
