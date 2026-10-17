-- Fator de evento da B3 (src/gold/eventos.py, notebook gold/b3): uma linha por ticker e pregão em que um
-- desdobramento, grupamento ou bonificação entra. É a única fonte do fator de evento: as cotações (fator_evento,
-- preço ajustado), os proventos (fator_posterior) e a validação externa leem esta tabela.

CREATE TABLE IF NOT EXISTS ${catalog}.gold.fct_evento_acao (
  ticker     STRING  NOT NULL,
  data_ex    DATE    NOT NULL COMMENT 'Pregão em que o evento entra (primeiro depois da data com)',
  data_com   DATE    COMMENT 'Última data com direito (heurística: pregão anterior)',
  fator      DOUBLE  NOT NULL COMMENT 'Preço depois = preço antes x fator (desdobramento 1:2 → 0,5; bonificação 10 % → 1/1,1)',
  origem     STRING  NOT NULL COMMENT 'B3, complementar (config/datasets/b3_eventos_complementares.yaml) ou heurística',
  detalhe    STRING  COMMENT 'Eventos que dão este fator (tipo, fator publicado, data com) ou a variação detetada',
  CONSTRAINT pk_fct_evento_acao PRIMARY KEY (ticker, data_ex) NOT ENFORCED
)
USING DELTA
CLUSTER BY (ticker)
COMMENT 'B3: fator de evento por ticker e data ex (desdobramentos, grupamentos, bonificações)';
