-- Fundamentos trimestrais das companhias abertas (reconstruído pelo notebook gold/cvm_fundamentos).
-- Valores do trimestre (3 meses): 1.º a 3.º trimestre da ITR; o 4.º = anual da DFP menos os três trimestres.
-- 12 meses = soma dos últimos 4 trimestres consecutivos. Consolidado quando existe, senão individual.
-- data_publicacao = primeira entrega do documento à CVM (a partir daí a informação é pública: usar esta data, e não
-- o fim do trimestre, para evitar olhar para o futuro). Os valores são os da versão mais recente do documento.

CREATE TABLE IF NOT EXISTS ${catalog}.gold.fct_fundamentos_trimestre (
  cnpj_cia            STRING         NOT NULL,
  dt_fim              DATE           NOT NULL COMMENT 'Fim do trimestre',
  documento           STRING         NOT NULL COMMENT 'ITR (1.º a 3.º trimestre) ou DFP (4.º)',
  escopo              STRING         NOT NULL COMMENT 'con ou ind',
  data_publicacao     DATE           COMMENT 'Primeira entrega à CVM',
  receita_tri         DECIMAL(24, 2),
  lucro_tri           DECIMAL(24, 2) COMMENT 'Atribuído aos controladores quando a DRE o separa',
  lair_tri            DECIMAL(24, 2) COMMENT 'Resultado antes dos tributos sobre o lucro',
  receita_12m         DECIMAL(24, 2),
  lucro_12m           DECIMAL(24, 2),
  ativo_total         DECIMAL(24, 2),
  patrimonio_liquido  DECIMAL(24, 2) COMMENT 'Dos controladores (consolidado menos não controladores)',
  divida_bruta        DECIMAL(24, 2) COMMENT 'Empréstimos e financiamentos (circulante + não circulante); NULL em bancos',
  caixa               DECIMAL(24, 2) COMMENT 'Caixa e equivalentes + aplicações financeiras de curto prazo',
  acoes_on            BIGINT         COMMENT 'Em circulação (integralizadas - tesouraria)',
  acoes_pn            BIGINT,
  acoes_total         BIGINT,
  CONSTRAINT pk_fct_fundamentos PRIMARY KEY (cnpj_cia, dt_fim) NOT ENFORCED
)
USING DELTA
CLUSTER BY (cnpj_cia, dt_fim)
COMMENT 'Fundamentos trimestrais (DFP/ITR): receita, lucro, PL, dívida, caixa e ações, com data de publicação';
