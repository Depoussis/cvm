# Databricks notebook source
# MAGIC %md
# MAGIC # Gold · fundamentos das companhias (DFP/ITR)
# MAGIC `fct_fundamentos_trimestre`: uma linha por companhia e trimestre, reconstruída a partir da silver. As contas são
# MAGIC identificadas pela descrição padronizada da CVM no nível certo do plano de contas, porque os códigos mudam entre
# MAGIC tipos de empresa (ex.: lucro consolidado é 3.11 na indústria, 3.09 nos bancos, 3.13 nas seguradoras; o PL é 2.03
# MAGIC ou 2.08). Ver docs/fundamentos.md.

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
from src.gold.fundamentos import SQL_FUNDAMENTOS
from src.quality import rules as dq

k = p.catalogo
e = control.Execucao(k, p.run_id, "gold_cvm_fundamentos", "cvm", "gold_cvm_fundamentos", "gold", p.run_mode)
control.iniciar(spark, e)
bloqueios = dq.falhas_bloqueantes(spark, k, p.run_id)
if bloqueios:
    erro = RuntimeError(f"publicação gold bloqueada por regras de qualidade: {bloqueios}")
    control.falhar(spark, e, erro)
    raise erro

contagens = control.Contagens()
try:
    spark.sql(f"INSERT OVERWRITE {k}.gold.fct_fundamentos_trimestre " + SQL_FUNDAMENTOS.format(k=k))
    fct = f"{k}.gold.fct_fundamentos_trimestre"
    contagens.inserted = spark.table(fct).count()
    print(f"gold.fct_fundamentos_trimestre: {contagens.inserted} linhas")
    regras = [
        dq.Regra("fundamentos_chave_unica", "Uma linha por (CNPJ, trimestre)", "CRITICAL", fct,
                 f"SELECT cnpj_cia, dt_fim, count(*) n FROM {fct} GROUP BY ALL HAVING n > 1",
                 f"SELECT count(*) FROM {fct}"),
        dq.Regra("sem_lucro_identificado", "Trimestre sem lucro identificado na DRE (descrição fora do padrão)", "INFO",
                 fct, f"SELECT cnpj_cia, dt_fim, documento FROM {fct} WHERE lucro_tri IS NULL",
                 f"SELECT count(*) FROM {fct}"),
        dq.Regra("sem_pl_identificado", "Trimestre sem património líquido identificado", "INFO", fct,
                 f"SELECT cnpj_cia, dt_fim FROM {fct} WHERE patrimonio_liquido IS NULL", f"SELECT count(*) FROM {fct}"),
        dq.Regra("publicacao_antes_do_fim", "Data de publicação anterior ao fim do trimestre", "INFO", fct,
                 f"SELECT cnpj_cia, dt_fim, data_publicacao FROM {fct} WHERE data_publicacao < dt_fim",
                 f"SELECT count(*) FROM {fct}"),
    ]
    resultados = dq.avaliar(spark, regras, amostra=10)
    dq.gravar(spark, k, p.run_id, resultados)
    for r in resultados:
        print(f"{r.regra.nome}: {'PASSED' if r.passou else 'FAILED'} ({r.falhados}/{r.avaliados}) {r.amostra[:5]}")
    if any(not r.passou and r.regra.severidade == "CRITICAL" for r in resultados):
        raise RuntimeError("regras críticas falharam nos fundamentos")
    control.concluir(spark, e, contagens)
except Exception as ex:
    control.falhar(spark, e, ex, contagens)
    raise

# COMMAND ----------

display(spark.sql(f"""SELECT f.*, a.ticker FROM {k}.gold.fct_fundamentos_trimestre f
                     JOIN {k}.gold.dim_ativo_b3 a ON a.cnpj_emissor = f.cnpj_cia
                     WHERE a.ticker IN ('PETR4', 'ITUB4', 'WEGE3') ORDER BY a.ticker, f.dt_fim DESC"""))
