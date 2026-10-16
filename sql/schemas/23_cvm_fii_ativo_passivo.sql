-- Silver: composição do ativo e passivo dos FII (ficheiro ativo_passivo do informe mensal), versão mais alta por mês.
-- Tabela separada de cvm_fii_mensal para não alterar o record_hash dessa (evita falsas reapresentações).
CREATE TABLE IF NOT EXISTS ${catalog}.silver.cvm_fii_ativo_passivo (
  cnpj_classe                  STRING         NOT NULL,
  data_referencia              DATE           NOT NULL,
  versao                       INT            NOT NULL,
  total_necessidades_liquidez  DECIMAL(20, 2) COMMENT 'Ativos para necessidades de liquidez (caixa e equivalentes)',
  disponibilidades             DECIMAL(20, 2),
  titulos_publicos             DECIMAL(20, 2),
  fundos_renda_fixa            DECIMAL(20, 2),
  total_investido              DECIMAL(20, 2),
  direitos_bens_imoveis        DECIMAL(20, 2),
  cri                          DECIMAL(20, 2),
  lci                          DECIMAL(20, 2),
  rendimentos_distribuir       DECIMAL(20, 2),
  total_passivo                DECIMAL(20, 2),
  record_hash                  STRING         NOT NULL,
  _inserted_at                 TIMESTAMP      NOT NULL,
  _updated_at                  TIMESTAMP      NOT NULL,
  _pipeline_run_id             STRING         NOT NULL,
  CONSTRAINT pk_cvm_fii_ativo_passivo PRIMARY KEY (cnpj_classe, data_referencia) NOT ENFORCED
)
USING DELTA
CLUSTER BY (data_referencia, cnpj_classe)
COMMENT 'CVM: ativo e passivo dos FII por mês (SCD1, versão mais alta)'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true');
