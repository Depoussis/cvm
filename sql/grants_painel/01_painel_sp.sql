-- Leitura para a identidade da GitHub Action que exporta o painel (aplicação findata-painel-github).
-- Corre UMA vez, por quem é dono do catálogo, com o client id da aplicação:
--   python scripts/apply_sql.py --env dev --dir sql/grants_painel --var sp=<client id>
-- Só leitura: não cria nem altera objetos e não lê volumes.
GRANT USE CATALOG, USE SCHEMA, SELECT ON CATALOG ${catalog} TO `${sp}`;
