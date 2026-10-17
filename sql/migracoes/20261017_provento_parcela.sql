-- Migração única (17/10/2026): parcelas de proventos. A B3 lista cada parcela de um provento como uma linha igual
-- (ex.: Petrobras, data com 25/04/2024, 2 x R$ 0,55015787); a chave antiga juntava-as numa só.
-- Corrida à mão uma vez; depois: job findata_<env>_b3_proventos (silver e gold) para recarregar as tabelas.
-- As tabelas novas já nascem com a coluna (sql/schemas/25_b3_proventos_silver.sql, sql/facts/45_b3_proventos.sql).

DELETE FROM ${catalog}.silver.b3_provento;
ALTER TABLE ${catalog}.silver.b3_provento ADD COLUMN parcela INT COMMENT 'Linhas iguais na fonte = parcelas do mesmo provento (1, 2, ...)' AFTER valor_por_acao;
ALTER TABLE ${catalog}.silver.b3_provento ALTER COLUMN parcela SET NOT NULL;
ALTER TABLE ${catalog}.silver.b3_provento DROP CONSTRAINT IF EXISTS pk_b3_provento;
ALTER TABLE ${catalog}.silver.b3_provento ADD CONSTRAINT pk_b3_provento PRIMARY KEY (emissor, tipo_acao, tipo_provento, data_com, valor_por_acao, parcela) NOT ENFORCED;

DELETE FROM ${catalog}.gold.fct_provento;
ALTER TABLE ${catalog}.gold.fct_provento ADD COLUMN parcela INT COMMENT 'Parcelas iguais do mesmo provento (1, 2, ...), FII sempre 1';
ALTER TABLE ${catalog}.gold.fct_provento ALTER COLUMN parcela SET NOT NULL;
ALTER TABLE ${catalog}.gold.fct_provento DROP CONSTRAINT IF EXISTS pk_fct_provento;
ALTER TABLE ${catalog}.gold.fct_provento ADD CONSTRAINT pk_fct_provento PRIMARY KEY (ticker, tipo_provento, data_com, valor_por_acao, parcela) NOT ENFORCED;
