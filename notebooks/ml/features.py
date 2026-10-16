# Databricks notebook source
# MAGIC %md
# MAGIC # ML · Features do ranking de ações
# MAGIC `gold.ml_features`: uma linha por (ação, data de referência) com as variáveis do modelo e o alvo, calculadas
# MAGIC sem olhar para o futuro (`src/ml/features.py`). Reconstruída a cada execução (~20 mil linhas).

# COMMAND ----------

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd().parents[1]))

from src.common import notebook

notebook.declarar(dbutils)
p = notebook.ler(dbutils)
print(p)

# COMMAND ----------

from src.audit import control
from src.ml.features import SQL_FEATURES
from src.quality import rules as dq

k = p.catalogo
tabela = f"{k}.gold.ml_features"
e = control.Execucao(k, p.run_id, "ml_features", "ml", "ml_features", "gold", p.run_mode)
control.iniciar(spark, e)
c = control.Contagens()
try:
    spark.sql(f"CREATE OR REPLACE TABLE {tabela} "
              f"COMMENT 'Modelo de ranking: variáveis por ação e data de referência (point-in-time) e retorno dos 21 "
              f"pregões seguintes' AS " + SQL_FEATURES.format(k=k))
    c.inserted = spark.table(tabela).count()
    regras = [
        dq.Regra("ml_features_chave_unica", "Uma linha por (ticker, data de referência)", "CRITICAL", tabela,
                 f"SELECT ticker, data_ref, count(*) n FROM {tabela} GROUP BY ALL HAVING n > 1",
                 f"SELECT count(*) FROM {tabela}"),
        # Garantias contra olhar para o futuro (devem dar sempre zero)
        dq.Regra("ml_fundamentos_publicados_antes", "Fundamentos publicados depois da data de referência", "CRITICAL",
                 tabela, f"SELECT ticker, data_ref, fundamentos_publicados FROM {tabela} "
                         f"WHERE fundamentos_publicados > data_ref", f"SELECT count(*) FROM {tabela}"),
        dq.Regra("ml_alvo_depois_da_referencia", "Fim do alvo não posterior à data de referência", "CRITICAL", tabela,
                 f"SELECT ticker, data_ref, data_fwd FROM {tabela} WHERE data_fwd <= data_ref",
                 f"SELECT count(*) FROM {tabela}"),
        dq.Regra("ml_cobertura_fundamentos", "Linhas sem fundamentos (empresa sem DFP/ITR ou sem CNPJ)", "INFO", tabela,
                 f"SELECT ticker, data_ref FROM {tabela} WHERE earnings_yield IS NULL",
                 f"SELECT count(*) FROM {tabela}"),
    ]
    resultados = dq.avaliar(spark, regras, amostra=10)
    dq.gravar(spark, k, p.run_id, resultados)
    for r in resultados:
        print(f"{r.regra.nome}: {'PASSED' if r.passou else 'FAILED'} ({r.falhados}/{r.avaliados}) {r.amostra[:3]}")
    if any(not r.passou and r.regra.severidade == "CRITICAL" for r in resultados):
        raise RuntimeError("regras críticas falharam nas features")
    control.concluir(spark, e, c)
except Exception as ex:
    control.falhar(spark, e, ex, c)
    raise

# COMMAND ----------

display(spark.sql(f"""SELECT data_ref, count(*) AS acoes, count(earnings_yield) AS com_fundamentos,
                             count(ret_fwd) AS com_alvo FROM {tabela} GROUP BY 1 ORDER BY 1"""))
