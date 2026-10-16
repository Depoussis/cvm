-- Facto diário de cotações da B3 (reconstruído pelo notebook gold/b3).
-- Ajuste a eventos: desdobramentos e grupamentos são detetados pela própria série (variação do fecho próxima de um
-- fator inteiro, ex.: 1/2, 1/10, 10, no mesmo dia em que muda o número de distribuição do papel). Dividendos e
-- bonificações não são ajustados: o retorno é de preço.

CREATE TABLE IF NOT EXISTS ${catalog}.gold.fct_cotacao_diaria (
  ticker            STRING         NOT NULL,
  data_pregao       DATE           NOT NULL,
  data_key          INT            NOT NULL,
  classe_ativo      STRING         NOT NULL,
  preco_abertura    DECIMAL(18, 6),
  preco_maximo      DECIMAL(18, 6),
  preco_minimo      DECIMAL(18, 6),
  preco_fechamento  DECIMAL(18, 6),
  negocios          INT,
  quantidade        BIGINT,
  volume            DECIMAL(20, 2),
  fator_evento      DOUBLE         COMMENT 'Fator do desdobramento (<1) ou grupamento (>1) detetado neste pregão; 1 sem evento',
  retorno_dia       DOUBLE         COMMENT 'Fecho / (fecho anterior x fator_evento) - 1; NULL no primeiro pregão',
  preco_ajustado    DOUBLE         COMMENT 'Fecho ajustado a desdobramentos/grupamentos posteriores (comparável com o último preço)',
  CONSTRAINT pk_fct_cotacao_diaria PRIMARY KEY (ticker, data_key) NOT ENFORCED,
  CONSTRAINT fk_fct_cotacao_data FOREIGN KEY (data_key) REFERENCES ${catalog}.gold.dim_data NOT ENFORCED,
  CONSTRAINT fk_fct_cotacao_ativo FOREIGN KEY (ticker) REFERENCES ${catalog}.gold.dim_ativo_b3 NOT ENFORCED
)
USING DELTA
CLUSTER BY (data_pregao, ticker)
COMMENT 'Cotações diárias da B3 (mercado à vista) com retorno de preço ajustado a desdobramentos';
