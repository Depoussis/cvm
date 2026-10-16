-- Dimensão dos papéis negociados na B3 (reconstruída pelo notebook gold/b3).

CREATE TABLE IF NOT EXISTS ${catalog}.gold.dim_ativo_b3 (
  ticker              STRING NOT NULL,
  classe_ativo        STRING NOT NULL COMMENT 'Ação, FII ou ETF e fundos',
  nome_pregao         STRING,
  especificacao       STRING,
  isin                STRING,
  cnpj_emissor        STRING COMMENT 'Companhia (FCA da CVM) ou FII (ISIN do informe mensal)',
  nome_emissor        STRING,
  setor               STRING COMMENT 'Setor de atividade da companhia (cadastro CVM) ou segmento do FII',
  segmento_listagem   STRING COMMENT 'Novo Mercado, Nível 1, Nível 2, Básico, ... (só ações)',
  tipo_papel          STRING COMMENT 'ON, PN ou Unit, pela especificação da B3 (só ações)',
  primeiro_pregao     DATE   COMMENT 'Primeiro pregão com negócios no histórico carregado',
  ultimo_pregao       DATE,
  CONSTRAINT pk_dim_ativo_b3 PRIMARY KEY (ticker) NOT ENFORCED
)
USING DELTA
COMMENT 'Papéis do mercado à vista da B3 (lote padrão, FII, ETF) com o emissor da CVM';
