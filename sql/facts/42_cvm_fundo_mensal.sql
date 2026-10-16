-- Rentabilidade mensal da cota (reconstruída pelo notebook gold/cvm a partir de fct_fundo_diario).

CREATE TABLE IF NOT EXISTS ${catalog}.gold.fct_fundo_mensal (
  cnpj_classe     STRING          NOT NULL,
  id_subclasse    STRING          NOT NULL,
  mes             DATE            NOT NULL COMMENT 'Primeiro dia do mês',
  cota_fim_mes    DECIMAL(27, 12) NOT NULL COMMENT 'Última cota informada no mês',
  pl_fim_mes      DECIMAL(17, 2),
  cotistas_fim_mes INT,
  captacao_mes    DECIMAL(20, 2),
  resgate_mes     DECIMAL(20, 2),
  dias_informados INT             NOT NULL,
  rentab_mes      DOUBLE          COMMENT 'cota_fim_mes / cota_fim do mês anterior - 1; NULL se o mês anterior faltar',
  CONSTRAINT pk_fct_fundo_mensal PRIMARY KEY (cnpj_classe, id_subclasse, mes) NOT ENFORCED
)
USING DELTA
CLUSTER BY (mes, cnpj_classe)
COMMENT 'Fundos/classes por mês: cota e PL de fim de mês, captação, resgate e rentabilidade mensal';
