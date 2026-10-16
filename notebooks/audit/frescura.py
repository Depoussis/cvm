# Databricks notebook source
# MAGIC %md
# MAGIC # Auditoria · Frescura dos dados
# MAGIC Falha (e por isso dispara o alerta do ADF) quando:
# MAGIC - o watermark de uma entidade está mais velho do que o permitido em `config/sla.yaml`;
# MAGIC - a última execução com sucesso de um pipeline bronze é mais antiga do que `execucao_max_horas`;
# MAGIC - há execuções presas em `RUNNING` há mais de 6 horas.
# MAGIC Grava cada verificação em `control.data_quality_results` (tabela `control.ingestion_watermark`).

# COMMAND ----------

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd().parents[1]))

from src.common import notebook

notebook.declarar(dbutils)
p = notebook.ler(dbutils)

# COMMAND ----------

from src.common.config import carregar_yaml
from src.quality import rules as dq

k = p.catalogo
sla = carregar_yaml("sla.yaml")
casos = []
for fonte, dias in sla["padrao_dias"].items():
    excecoes = sla["entidades"].get(fonte) or {}
    limite = " ".join(f"WHEN '{e}' THEN {d}" for e, d in excecoes.items())
    casos.append(f"(source_system = '{fonte}' AND datediff(current_date(), to_date(watermark_value)) > "
                 f"CASE entity_name {limite} ELSE {dias} END)" if limite else
                 f"(source_system = '{fonte}' AND datediff(current_date(), to_date(watermark_value)) > {dias})")
wm = f"{k}.control.ingestion_watermark"
execucoes = f"{k}.control.pipeline_execution"
max_h = " ".join(f"WHEN '{n}' THEN {h}" for n, h in sla["execucao_max_horas"].items())
nomes = ", ".join(f"'{n}'" for n in sla["execucao_max_horas"])

regras = [
    dq.Regra("watermark_dentro_do_sla", "Última data de referência dentro do prazo de config/sla.yaml", "HIGH", wm,
             f"SELECT source_system, entity_name, watermark_value, datediff(current_date(), to_date(watermark_value)) AS dias "
             f"FROM {wm} WHERE watermark_type = 'reference_date' AND ({' OR '.join(casos)})",
             f"SELECT count(*) FROM {wm} WHERE watermark_type = 'reference_date'"),
    dq.Regra("execucao_recente", "Pipelines bronze com sucesso dentro de execucao_max_horas", "HIGH", execucoes,
             f"""SELECT n.pipeline_name, max(e.end_timestamp) AS ultimo_sucesso
                 FROM (SELECT explode(array({nomes})) AS pipeline_name) n
                 LEFT JOIN {execucoes} e ON e.pipeline_name = n.pipeline_name AND e.execution_status = 'SUCCEEDED'
                 GROUP BY 1
                 HAVING ultimo_sucesso IS NULL OR
                        ultimo_sucesso < current_timestamp() - make_interval(0, 0, 0, 0,
                                         CASE n.pipeline_name {max_h} END, 0, 0)""",
             f"SELECT size(array({nomes}))"),
    dq.Regra("sem_execucoes_presas", "Nenhuma execução em RUNNING há mais de 6 horas", "HIGH", execucoes,
             f"SELECT pipeline_run_id, pipeline_name, entity_name, start_timestamp FROM {execucoes} "
             f"WHERE execution_status = 'RUNNING' AND start_timestamp < current_timestamp() - INTERVAL 6 HOURS",
             f"SELECT count(*) FROM {execucoes} WHERE execution_status = 'RUNNING'"),
]
resultados = dq.avaliar(spark, regras, amostra=20)
dq.gravar(spark, k, p.run_id, resultados)
for r in resultados:
    print(f"{r.regra.nome}: {'PASSED' if r.passou else 'FAILED'} ({r.falhados}/{r.avaliados}) {r.amostra}")
falhas = [f"{r.regra.nome}: {r.amostra}" for r in resultados if not r.passou]
if falhas:
    raise RuntimeError(f"dados fora do prazo: {falhas}")
