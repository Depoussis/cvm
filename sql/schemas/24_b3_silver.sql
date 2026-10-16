-- Silver da B3 e do FCA da CVM.

-- Uma linha por (pregão, ticker) do mercado à vista, só lote padrão, FII e ETF/fundos (config/datasets/b3.yaml).
-- Preços em reais por unidade (já divididos pelo fator de cotação). Sem ajuste a proventos: é o preço negociado.
CREATE TABLE IF NOT EXISTS ${catalog}.silver.b3_cotacao_diaria (
  data_pregao       DATE           NOT NULL,
  ticker            STRING         NOT NULL,
  codbdi            STRING         NOT NULL,
  classe_ativo      STRING         NOT NULL COMMENT 'Ação, FII ou ETF e fundos',
  nome_pregao       STRING,
  especificacao     STRING         COMMENT 'Ex.: ON NM, PN N2, UNT, CI',
  isin              STRING,
  distribuicao      INT            COMMENT 'Número de distribuição (DISMES); muda com proventos e eventos',
  preco_abertura    DECIMAL(18, 6),
  preco_maximo      DECIMAL(18, 6),
  preco_minimo      DECIMAL(18, 6),
  preco_medio       DECIMAL(18, 6),
  preco_fechamento  DECIMAL(18, 6),
  negocios          INT,
  quantidade        BIGINT,
  volume            DECIMAL(20, 2) COMMENT 'Volume financeiro em reais',
  fator_cotacao     INT,
  record_hash       STRING         NOT NULL,
  _inserted_at      TIMESTAMP      NOT NULL,
  _updated_at       TIMESTAMP      NOT NULL,
  _pipeline_run_id  STRING         NOT NULL,
  CONSTRAINT pk_b3_cotacao_diaria PRIMARY KEY (data_pregao, ticker) NOT ENFORCED
)
USING DELTA
CLUSTER BY (data_pregao, ticker)
COMMENT 'B3: cotações diárias do mercado à vista (SCD1)'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true');

-- Ticker -> companhia (FCA, valores mobiliários negociados em bolsa). Reconstruída a cada carga a partir de toda a
-- bronze: por ticker fica o formulário mais recente (data de referência e versão mais altas).
CREATE TABLE IF NOT EXISTS ${catalog}.silver.cvm_valor_mobiliario (
  ticker                  STRING NOT NULL,
  cnpj_cia                STRING NOT NULL,
  nome_empresarial        STRING,
  valor_mobiliario        STRING COMMENT 'Ações Ordinárias, Ações Preferenciais, Units, ...',
  classe_preferencial     STRING,
  segmento_listagem       STRING COMMENT 'Novo Mercado, Nível 1, Nível 2, Básico, Bovespa Mais',
  data_inicio_negociacao  DATE,
  data_fim_negociacao     DATE,
  data_referencia         DATE   NOT NULL COMMENT 'Data de referência do FCA de onde vem a linha',
  versao                  INT,
  record_hash             STRING NOT NULL,
  _inserted_at            TIMESTAMP NOT NULL,
  _updated_at             TIMESTAMP NOT NULL,
  _pipeline_run_id        STRING NOT NULL,
  CONSTRAINT pk_cvm_valor_mobiliario PRIMARY KEY (ticker) NOT ENFORCED
)
USING DELTA
COMMENT 'CVM FCA: ticker negociado na B3 por companhia aberta (SCD1, formulário mais recente)';
