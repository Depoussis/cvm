# Databricks notebook source
# MAGIC %md
# MAGIC # Criação das tabelas de controlo
# MAGIC Aplica `sql/control/*.sql` no catálogo do ambiente. Idempotente: pode ser executado várias vezes.
# MAGIC Alternativa sem cluster: `python scripts/apply_sql.py --env dev --dir sql/control` (SQL Warehouse).

# COMMAND ----------

dbutils.widgets.dropdown("env", "dev", ["dev", "test", "prod"])
env = dbutils.widgets.get("env")

# COMMAND ----------

import sys
from pathlib import Path

# O notebook corre dentro da pasta Git do workspace; a raiz do repositório fica dois níveis acima.
raiz = Path.cwd().parents[1]
sys.path.insert(0, str(raiz))

from src.common.config import carregar_ambiente
from src.common.sql_files import carregar_ficheiros

cfg = carregar_ambiente(env)
catalogo = cfg["unity_catalog"]["catalog"]

# COMMAND ----------

for ficheiro, instrucao in carregar_ficheiros(raiz / "sql" / "control", {"catalog": catalogo}):
    spark.sql(instrucao)
    print(f"{ficheiro}: ok  {' '.join(instrucao.split())[:100]}")

# COMMAND ----------

display(spark.sql(f"SHOW TABLES IN {catalogo}.control"))
