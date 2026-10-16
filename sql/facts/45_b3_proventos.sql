-- Proventos por ticker (reconstruído pelo notebook gold/b3_proventos). Ações: dividendos/JCP da B3. FII: rendimento
-- por cota estimado pelo informe mensal da CVM (DY x cota patrimonial; tipo 'RENDIMENTO FII (CVM)').
-- A B3 publica o provento por emissor e espécie (ON, PN, UNT...); o ticker é o papel da mesma raiz cuja
-- especificação começa por essa espécie. Data ex = primeiro pregão do ticker depois da data com.

CREATE TABLE IF NOT EXISTS ${catalog}.gold.fct_provento (
  ticker                  STRING          NOT NULL,
  emissor                 STRING          NOT NULL,
  tipo_acao               STRING          NOT NULL,
  tipo_provento           STRING          NOT NULL,
  data_com                DATE            NOT NULL,
  data_ex                 DATE            COMMENT 'Primeiro pregão depois da data com (NULL se ainda não houve)',
  data_aprovacao          DATE,
  valor_por_acao          DECIMAL(24, 11) NOT NULL COMMENT 'Na base de ações da data com',
  fecho_data_com          DECIMAL(18, 6)  COMMENT 'Último fecho do ticker até à data com (COTAHIST)',
  yield_evento            DOUBLE          COMMENT 'valor_por_acao / fecho_data_com (fração)',
  fator_posterior         DOUBLE          COMMENT 'Produto dos fatores de desdobramento/grupamento depois da data com',
  valor_ajustado          DOUBLE          COMMENT 'valor_por_acao x fator_posterior: comparável com o preço atual',
  CONSTRAINT pk_fct_provento PRIMARY KEY (ticker, tipo_provento, data_com, valor_por_acao) NOT ENFORCED
)
USING DELTA
CLUSTER BY (ticker, data_com)
COMMENT 'Dividendos, JCP e rendimentos por ticker, com data ex e yield do evento';
