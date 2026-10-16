-- Consultas "como a plataforma conhecia o cadastro num dado momento" sobre as tabelas SCD2.
-- valid_from/valid_to são tempo de processamento (quando a mudança foi carregada), não a data de vigência
-- declarada pela fonte; para datas de negócio usar as colunas da fonte (ex.: data_inicio_situacao, dt_ini_sit).

CREATE OR REPLACE FUNCTION ${catalog}.gold.fn_fundo_classe_em(momento TIMESTAMP)
RETURNS TABLE (id_registro_classe STRING, cnpj_classe STRING, denominacao_social STRING, tipo_classe STRING,
               situacao STRING, classificacao STRING, classificacao_anbima STRING, publico_alvo STRING,
               valid_from TIMESTAMP, valid_to TIMESTAMP)
COMMENT 'Classes de fundos tal como estavam carregadas no momento indicado'
RETURN SELECT id_registro_classe, cnpj_classe, denominacao_social, tipo_classe, situacao, classificacao,
              classificacao_anbima, publico_alvo, valid_from, valid_to
       FROM ${catalog}.silver.cvm_fundo_classe
       WHERE valid_from <= momento AND (valid_to IS NULL OR valid_to > momento);

CREATE OR REPLACE FUNCTION ${catalog}.gold.fn_companhia_em(momento TIMESTAMP)
RETURNS TABLE (cd_cvm STRING, cnpj_cia STRING, denom_social STRING, sit STRING, categ_reg STRING, tp_merc STRING,
               setor_ativ STRING, valid_from TIMESTAMP, valid_to TIMESTAMP)
COMMENT 'Companhias abertas tal como estavam carregadas no momento indicado'
RETURN SELECT cd_cvm, cnpj_cia, denom_social, sit, categ_reg, tp_merc, setor_ativ, valid_from, valid_to
       FROM ${catalog}.silver.cvm_companhia
       WHERE valid_from <= momento AND (valid_to IS NULL OR valid_to > momento);

-- Histórico de alterações de cada companhia (uma linha por versão).
CREATE OR REPLACE VIEW ${catalog}.gold.vw_companhia_historico
COMMENT 'Versões do cadastro de companhias abertas (SCD2), da mais recente para a mais antiga'
AS
SELECT cd_cvm, cnpj_cia, denom_social, sit, categ_reg, tp_merc, valid_from, valid_to, is_current
FROM ${catalog}.silver.cvm_companhia;

-- Reapresentações por tabela e mês de referência.
CREATE OR REPLACE VIEW ${catalog}.gold.vw_reapresentacoes_resumo
COMMENT 'Quantos valores já publicados foram revistos, por tabela, dia de deteção e execução'
AS
SELECT table_name, date(commit_timestamp) AS dia, pipeline_run_id, count(*) AS alteracoes,
       array_distinct(flatten(collect_list(colunas_alteradas))) AS colunas
FROM ${catalog}.control.reapresentacoes
GROUP BY ALL;
