# Databricks notebook source
# MAGIC %md
# MAGIC # Gold · Banco Central
# MAGIC Publica as dimensões e factos a partir da silver, só se a execução não tiver falhas de qualidade bloqueantes.
# MAGIC Reconstrução completa com `INSERT OVERWRITE` (os volumes BCB são pequenos), por isso repetir é seguro.
# MAGIC No fim, reconcilia a série SGS 1 (dólar venda) com a PTAX de fechamento USD (regra INFO).

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
from src.quality import rules as dq

k = p.catalogo
e = control.Execucao(k, p.run_id, "gold_bcb", "bcb", "gold_bcb", "gold", p.run_mode)
control.iniciar(spark, e)

bloqueios = dq.falhas_bloqueantes(spark, k, p.run_id)
if bloqueios:
    erro = RuntimeError(f"publicação gold bloqueada por regras de qualidade: {bloqueios}")
    control.falhar(spark, e, erro)
    raise erro

# COMMAND ----------

PUBLICACAO = {
    "dim_serie": f"""
        INSERT OVERWRITE {k}.gold.dim_serie
        SELECT serie_codigo, nome, responsavel, periodicidade, dataset_bcb
        FROM {k}.silver.bcb_sgs_series WHERE is_current""",
    "dim_moeda": f"""
        INSERT OVERWRITE {k}.gold.dim_moeda
        SELECT simbolo, nome_formatado, tipo_moeda FROM {k}.silver.bcb_ptax_moedas WHERE is_current""",
    "fct_serie_valor": f"""
        INSERT OVERWRITE {k}.gold.fct_serie_valor
        SELECT v.serie_codigo, CAST(date_format(v.data_referencia, 'yyyyMMdd') AS INT), v.data_referencia, v.valor
        FROM {k}.silver.bcb_sgs_valores v
        JOIN {k}.gold.dim_serie s ON s.serie_codigo = v.serie_codigo""",
    "fct_ptax_diario": f"""
        INSERT OVERWRITE {k}.gold.fct_ptax_diario
        SELECT c.moeda, CAST(date_format(c.data_cotacao, 'yyyyMMdd') AS INT), c.data_cotacao,
               c.cotacao_compra, c.cotacao_venda, c.paridade_compra, c.paridade_venda
        FROM {k}.silver.bcb_ptax_cotacoes c
        JOIN {k}.gold.dim_moeda m ON m.simbolo = c.moeda
        WHERE c.tipo_boletim = 'Fechamento'
        -- fechamento repetido pela fonte no mesmo dia: fica o último publicado
        QUALIFY row_number() OVER (PARTITION BY c.moeda, c.data_cotacao ORDER BY c.data_hora_cotacao DESC) = 1""",
}

contagens = control.Contagens()
try:
    for tabela, sql in PUBLICACAO.items():
        spark.sql(sql)
        n = spark.table(f"{k}.gold.{tabela}").count()
        contagens.inserted += n
        print(f"gold.{tabela}: {n} linhas")

    total = f"SELECT count(*) FROM {k}.gold.fct_serie_valor WHERE serie_codigo = 1"
    regras = [
        dq.Regra("fct_ptax_diario_chave_unica", "Uma linha por (moeda, dia)", "CRITICAL", f"{k}.gold.fct_ptax_diario",
                 f"SELECT simbolo, data_key, count(*) n FROM {k}.gold.fct_ptax_diario GROUP BY 1, 2 HAVING n > 1",
                 f"SELECT count(*) FROM {k}.gold.fct_ptax_diario"),
        dq.Regra("fct_serie_valor_dentro_do_calendario", "Todas as datas existem em dim_data", "HIGH",
                 f"{k}.gold.fct_serie_valor",
                 f"SELECT f.* FROM {k}.gold.fct_serie_valor f LEFT ANTI JOIN {k}.gold.dim_data d USING (data_key)",
                 f"SELECT count(*) FROM {k}.gold.fct_serie_valor"),
        dq.Regra("reconciliacao_sgs1_ptax_usd", "SGS 1 (dólar venda) igual à PTAX USD de fechamento (venda)", "INFO",
                 f"{k}.gold.fct_serie_valor",
                 f"""SELECT f.data_referencia, f.valor AS sgs_1, p.cotacao_venda AS ptax_usd
                     FROM {k}.gold.fct_serie_valor f
                     JOIN {k}.gold.fct_ptax_diario p ON p.data_key = f.data_key AND p.simbolo = 'USD'
                     WHERE f.serie_codigo = 1 AND abs(f.valor - p.cotacao_venda) > 0.00005""", total),
    ]
    resultados = dq.avaliar(spark, regras)
    dq.gravar(spark, k, p.run_id, resultados)
    for r in resultados:
        print(f"{r.regra.nome}: {'PASSED' if r.passou else 'FAILED'} ({r.falhados}/{r.avaliados}) {r.amostra[:3]}")
    control.concluir(spark, e, contagens)
except Exception as ex:
    control.falhar(spark, e, ex, contagens)
    raise

# COMMAND ----------

display(spark.sql(f"SELECT * FROM {k}.gold.vw_serie_ultimo_valor ORDER BY serie_codigo"))
