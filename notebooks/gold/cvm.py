# Databricks notebook source
# MAGIC %md
# MAGIC # Gold · CVM
# MAGIC - Bloqueia a publicação se a execução tiver falhas de qualidade CRITICAL/HIGH.
# MAGIC - `dim_fundo_classe`, `dim_companhia`: reconstruídas a partir da versão atual (SCD2) da silver.
# MAGIC - `fct_fundo_diario`: substitui só o intervalo afetado (`INSERT ... REPLACE WHERE`), desde o primeiro mês alterado
# MAGIC   nesta execução; `backfill`/`reprocess` reconstroem tudo. A rentabilidade diária usa a cota do informe anterior.

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
e = control.Execucao(k, p.run_id, "gold_cvm", "cvm", "gold_cvm", "gold", p.run_mode)
control.iniciar(spark, e)
bloqueios = dq.falhas_bloqueantes(spark, k, p.run_id)
if bloqueios:
    erro = RuntimeError(f"publicação gold bloqueada por regras de qualidade: {bloqueios}")
    control.falhar(spark, e, erro)
    raise erro

# COMMAND ----------

DIM_FUNDO_CLASSE = f"""
INSERT OVERWRITE {k}.gold.dim_fundo_classe
WITH fundo AS (
  SELECT * FROM {k}.silver.cvm_fundo WHERE is_current
),
classe AS (
  SELECT c.*, row_number() OVER (PARTITION BY c.cnpj_classe ORDER BY c.data_registro DESC NULLS LAST,
                                 c.id_registro_classe DESC) AS rn
  FROM {k}.silver.cvm_fundo_classe c WHERE c.is_current
),
fundo_sem_classe AS (
  SELECT f.*, row_number() OVER (PARTITION BY f.cnpj_fundo ORDER BY f.data_registro DESC NULLS LAST,
                                 f.id_registro_fundo DESC) AS rn
  FROM fundo f LEFT ANTI JOIN classe c ON c.cnpj_classe = f.cnpj_fundo
)
SELECT c.cnpj_classe, c.denominacao_social, 'classe', c.tipo_classe, c.classificacao, c.classificacao_anbima,
       c.situacao, c.publico_alvo, c.forma_condominio, c.exclusivo, f.cnpj_fundo, f.denominacao_social,
       f.tipo_fundo, f.cnpj_administrador, f.administrador
FROM classe c LEFT JOIN fundo f ON f.id_registro_fundo = c.id_registro_fundo
WHERE c.rn = 1
UNION ALL
SELECT f.cnpj_fundo, f.denominacao_social, 'fundo', NULL, NULL, NULL, f.situacao, NULL, NULL, NULL,
       f.cnpj_fundo, f.denominacao_social, f.tipo_fundo, f.cnpj_administrador, f.administrador
FROM fundo_sem_classe f WHERE f.rn = 1
"""

DIM_COMPANHIA = f"""
INSERT OVERWRITE {k}.gold.dim_companhia
SELECT cd_cvm, cnpj_cia, denom_social, denom_comerc, setor_ativ, sit, categ_reg, tp_merc, controle_acionario,
       mun, uf, auditor
FROM {k}.silver.cvm_companhia WHERE is_current
"""

contagens = control.Contagens()
try:
    for nome, sql in (("dim_fundo_classe", DIM_FUNDO_CLASSE), ("dim_companhia", DIM_COMPANHIA)):
        spark.sql(sql)
        n = spark.table(f"{k}.gold.{nome}").count()
        contagens.inserted += n
        print(f"gold.{nome}: {n} linhas")

    # Intervalo a substituir no facto
    if p.run_mode in {"backfill", "reprocess"}:
        inicio = spark.sql(f"SELECT min(dt_comptc) FROM {k}.silver.cvm_fi_informe_diario").first()[0]
    else:
        inicio = spark.sql(f"""SELECT trunc(min(dt_comptc), 'MM') FROM {k}.silver.cvm_fi_informe_diario
                               WHERE _pipeline_run_id = '{p.run_id}'""").first()[0]
    if inicio is None:
        print("fct_fundo_diario: sem alterações na silver nesta execução")
    else:
        spark.sql(f"""
            INSERT INTO {k}.gold.fct_fundo_diario REPLACE WHERE dt_comptc >= DATE'{inicio}'
            SELECT cnpj_classe, id_subclasse, CAST(date_format(dt_comptc, 'yyyyMMdd') AS INT), dt_comptc,
                   vl_quota, vl_patrim_liq, captc_dia, resg_dia,
                   CAST(coalesce(captc_dia, 0) - coalesce(resg_dia, 0) AS DECIMAL(18, 2)),
                   nr_cotst,
                   CASE WHEN cota_anterior > 0 THEN CAST(vl_quota AS DOUBLE) / CAST(cota_anterior AS DOUBLE) - 1 END
            FROM (
              SELECT *, lag(vl_quota) OVER (PARTITION BY cnpj_classe, id_subclasse ORDER BY dt_comptc) AS cota_anterior
              FROM {k}.silver.cvm_fi_informe_diario
              WHERE dt_comptc >= date_sub(DATE'{inicio}', 40)   -- inclui o informe anterior ao intervalo
            )
            WHERE dt_comptc >= DATE'{inicio}'
        """)
        n = spark.sql(f"SELECT count(*) FROM {k}.gold.fct_fundo_diario WHERE dt_comptc >= DATE'{inicio}'").first()[0]
        contagens.inserted += n
        print(f"gold.fct_fundo_diario: {n} linhas substituídas desde {inicio}")

    # Facto mensal (reconstrução completa: ~800 mil linhas a partir do diário)
    spark.sql(f"""
        INSERT OVERWRITE {k}.gold.fct_fundo_mensal
        WITH m AS (
          SELECT cnpj_classe, id_subclasse, CAST(date_trunc('MONTH', dt_comptc) AS DATE) AS mes,
                 max_by(vl_quota, dt_comptc) AS cota_fim_mes, max_by(vl_patrim_liq, dt_comptc) AS pl_fim_mes,
                 max_by(nr_cotst, dt_comptc) AS cotistas_fim_mes,
                 CAST(sum(captc_dia) AS DECIMAL(20,2)) AS captacao_mes, CAST(sum(resg_dia) AS DECIMAL(20,2)) AS resgate_mes,
                 count(*) AS dias_informados
          FROM {k}.gold.fct_fundo_diario WHERE vl_quota > 0
          GROUP BY ALL
        )
        SELECT cnpj_classe, id_subclasse, mes, cota_fim_mes, pl_fim_mes, cotistas_fim_mes, captacao_mes, resgate_mes,
               dias_informados,
               CASE WHEN lag(mes) OVER w = add_months(mes, -1)
                    THEN CAST(cota_fim_mes AS DOUBLE) / CAST(lag(cota_fim_mes) OVER w AS DOUBLE) - 1 END
        FROM m
        WINDOW w AS (PARTITION BY cnpj_classe, id_subclasse ORDER BY mes)
    """)
    n = spark.table(f"{k}.gold.fct_fundo_mensal").count()
    contagens.inserted += n
    print(f"gold.fct_fundo_mensal: {n} linhas")

    regras = [
        dq.Regra("fct_fundo_mensal_chave_unica", "Uma linha por (CNPJ, subclasse, mês)", "CRITICAL",
                 f"{k}.gold.fct_fundo_mensal",
                 f"SELECT cnpj_classe, id_subclasse, mes, count(*) n FROM {k}.gold.fct_fundo_mensal "
                 f"GROUP BY ALL HAVING n > 1", f"SELECT count(*) FROM {k}.gold.fct_fundo_mensal"),
        dq.Regra("pl_nao_negativo", "Património líquido de fim de mês não negativo", "INFO",
                 f"{k}.gold.fct_fundo_mensal",
                 f"SELECT cnpj_classe, mes, pl_fim_mes FROM {k}.gold.fct_fundo_mensal WHERE pl_fim_mes < 0",
                 f"SELECT count(*) FROM {k}.gold.fct_fundo_mensal"),
        dq.Regra("rentab_mensal_extrema", "Rentabilidade mensal acima de ±50 % (provável erro de cota)", "INFO",
                 f"{k}.gold.fct_fundo_mensal",
                 f"SELECT cnpj_classe, id_subclasse, mes, rentab_mes FROM {k}.gold.fct_fundo_mensal "
                 f"WHERE abs(rentab_mes) >= 0.5", f"SELECT count(*) FROM {k}.gold.fct_fundo_mensal WHERE rentab_mes IS NOT NULL"),
        dq.Regra("fct_fundo_diario_chave_unica", "Uma linha por (CNPJ, subclasse, dia)", "CRITICAL",
                 f"{k}.gold.fct_fundo_diario",
                 f"SELECT cnpj_classe, id_subclasse, data_key, count(*) n FROM {k}.gold.fct_fundo_diario "
                 f"GROUP BY ALL HAVING n > 1", f"SELECT count(*) FROM {k}.gold.fct_fundo_diario"),
        dq.Regra("dim_fundo_classe_chave_unica", "Um registo por CNPJ", "CRITICAL", f"{k}.gold.dim_fundo_classe",
                 f"SELECT cnpj_classe, count(*) n FROM {k}.gold.dim_fundo_classe GROUP BY 1 HAVING n > 1",
                 f"SELECT count(*) FROM {k}.gold.dim_fundo_classe"),
        dq.Regra("cobertura_cadastro", "CNPJ do informe encontrado no cadastro de fundos/classes", "INFO",
                 f"{k}.gold.fct_fundo_diario",
                 f"SELECT DISTINCT f.cnpj_classe FROM {k}.gold.fct_fundo_diario f "
                 f"LEFT ANTI JOIN {k}.gold.dim_fundo_classe d USING (cnpj_classe)",
                 f"SELECT count(DISTINCT cnpj_classe) FROM {k}.gold.fct_fundo_diario"),
    ]
    resultados = dq.avaliar(spark, regras)
    dq.gravar(spark, k, p.run_id, resultados)
    for r in resultados:
        print(f"{r.regra.nome}: {'PASSED' if r.passou else 'FAILED'} ({r.falhados}/{r.avaliados}) {r.amostra[:3]}")
    criticas = [r.regra.nome for r in resultados if not r.passou and r.regra.severidade == "CRITICAL"]
    if criticas:
        raise RuntimeError(f"regras críticas falharam na gold: {criticas}")
    control.concluir(spark, e, contagens)
except Exception as ex:
    control.falhar(spark, e, ex, contagens)
    raise

# COMMAND ----------

display(spark.sql(f"SELECT * FROM {k}.gold.vw_fundos_maiores_pl ORDER BY posicao LIMIT 20"))
