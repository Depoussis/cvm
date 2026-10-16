-- Permissões da identidade de deploy do Azure DevOps (service connection sc-findata-<env>) no Unity Catalog.
-- Corre UMA vez, por quem é dono do catálogo (o administrador), com o ID da aplicação (client id) da identidade:
--   python scripts/apply_sql.py --env dev --dir sql/grants --var sp=<client id>
-- O CD precisa de criar/alterar tabelas, vistas e funções (CREATE OR REPLACE exige MANAGE ou ser dono) e de ler
-- dados para o painel e o teste de fumaça. Não recebe acesso às credenciais de armazenamento.
GRANT USE CATALOG, USE SCHEMA, SELECT, MODIFY, CREATE TABLE, CREATE FUNCTION, CREATE VOLUME, READ VOLUME,
      WRITE VOLUME, EXECUTE, MANAGE
  ON CATALOG ${catalog} TO `${sp}`;
