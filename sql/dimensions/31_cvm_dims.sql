-- Dimensões gold da CVM (reconstruídas pelo notebook gold/cvm).

CREATE TABLE IF NOT EXISTS ${catalog}.gold.dim_fundo_classe (
  cnpj_classe          STRING NOT NULL COMMENT 'CNPJ da classe (RCVM 175) ou do fundo não adaptado, 14 dígitos',
  denominacao_social   STRING,
  origem_cadastro      STRING NOT NULL COMMENT 'classe (registro_classe) ou fundo (registro_fundo, sem classe)',
  tipo_classe          STRING,
  classificacao        STRING,
  classificacao_anbima STRING,
  situacao             STRING,
  publico_alvo         STRING,
  forma_condominio     STRING,
  exclusivo            STRING,
  cnpj_fundo           STRING,
  nome_fundo           STRING,
  tipo_fundo           STRING,
  cnpj_administrador   STRING,
  administrador        STRING,
  CONSTRAINT pk_dim_fundo_classe PRIMARY KEY (cnpj_classe) NOT ENFORCED
)
USING DELTA
COMMENT 'Fundos/classes de investimento (versão atual do cadastro CVM)';

CREATE TABLE IF NOT EXISTS ${catalog}.gold.dim_companhia (
  cd_cvm             STRING NOT NULL,
  cnpj_cia           STRING NOT NULL,
  denom_social       STRING,
  denom_comerc       STRING,
  setor_ativ         STRING,
  sit                STRING,
  categ_reg          STRING,
  tp_merc            STRING,
  controle_acionario STRING,
  mun                STRING,
  uf                 STRING,
  auditor            STRING,
  CONSTRAINT pk_dim_companhia PRIMARY KEY (cd_cvm) NOT ENFORCED
)
USING DELTA
COMMENT 'Companhias abertas (versão atual do cadastro CVM)';
