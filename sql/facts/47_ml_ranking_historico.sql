-- Histórico dos rankings publicados pelo modelo (notebook ml/treino), para acompanhar o modelo com dados reais.
-- Só recebe inserções: um ranking, depois de gravado, nunca é reescrito (MERGE ... WHEN NOT MATCHED INSERT). Assim o
-- resultado medido em gold.vw_ml_acompanhamento é o de previsões feitas antes de os preços existirem, e não pode ser
-- ajustado depois (ao contrário do backtest, que é recalculado a cada treino).

CREATE TABLE IF NOT EXISTS ${catalog}.gold.ml_ranking_historico (
  data_ref      DATE      NOT NULL COMMENT 'Último pregão com dados quando o ranking foi calculado',
  ticker        STRING    NOT NULL,
  setor         STRING,
  score         DOUBLE    COMMENT 'Probabilidade estimada de render acima da mediana nos 21 pregões seguintes',
  posicao       INT       COMMENT '1 = maior pontuação',
  modelo        STRING    COMMENT 'Modelo registado no Unity Catalog e versão',
  publicado_em  TIMESTAMP COMMENT 'Quando o ranking foi gravado pela primeira vez',
  CONSTRAINT pk_ml_ranking_historico PRIMARY KEY (data_ref, ticker) NOT ENFORCED
)
USING DELTA
CLUSTER BY (data_ref)
COMMENT 'Modelo de ranking: rankings publicados (só inserções, nunca reescritos), base do acompanhamento ao vivo';
