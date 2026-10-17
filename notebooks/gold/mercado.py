# Databricks notebook source
# MAGIC %md
# MAGIC # Gold · Referências de mercado
# MAGIC Reconstrução completa (tabelas pequenas) a partir da silver:
# MAGIC - `fct_indice_diario`: fecho e retorno diário dos índices oficiais da B3, com o nome do índice;
# MAGIC - `fct_tesouro_diario`: preços e taxas do Tesouro Direto, com o nome do título e o indexador.
# MAGIC A publicação fica bloqueada se houver falhas críticas de qualidade nesta execução.

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
from src.common.config import carregar_yaml
from src.quality import rules as dq

k = p.catalogo
nomes = carregar_yaml("datasets/mercado.yaml")["indices_b3"]["indices"]
e = control.Execucao(k, p.run_id, "gold_mercado", "mercado", "gold_mercado", "gold", p.run_mode)
control.iniciar(spark, e)
bloqueios = dq.falhas_bloqueantes(spark, k, p.run_id)
if bloqueios:
    erro = RuntimeError(f"publicação gold bloqueada por regras de qualidade: {bloqueios}")
    control.falhar(spark, e, erro)
    raise erro

nome_sql = "CASE indice " + " ".join(f"WHEN '{c}' THEN '{n}'" for c, n in nomes.items()) + " END"
INDICES = f"""
INSERT OVERWRITE {k}.gold.fct_indice_diario
SELECT indice, {nome_sql}, data_pregao, fechamento,
       CAST(fechamento AS DOUBLE) / CAST(lag(fechamento) OVER (PARTITION BY indice ORDER BY data_pregao) AS DOUBLE) - 1
FROM {k}.silver.b3_indice_diario
"""
TESOURO = f"""
INSERT OVERWRITE {k}.gold.fct_tesouro_diario
SELECT concat(tipo_titulo, ' ', year(data_vencimento)), tipo_titulo,
       CASE WHEN tipo_titulo LIKE '%IPCA%' OR tipo_titulo LIKE '%Renda+%' OR tipo_titulo LIKE '%Educa+%' THEN 'IPCA'
            WHEN tipo_titulo LIKE '%Selic%' THEN 'Selic' WHEN tipo_titulo LIKE '%IGPM%' THEN 'IGP-M'
            WHEN tipo_titulo LIKE '%Prefixado%' THEN 'Prefixado' END,
       tipo_titulo LIKE '%Juros Semestrais%', data_vencimento, data_base, taxa_compra, taxa_venda, pu_compra,
       pu_venda, pu_base
FROM {k}.silver.tesouro_preco_taxa
"""

contagens = control.Contagens()
try:
    for nome, sql in (("fct_indice_diario", INDICES), ("fct_tesouro_diario", TESOURO)):
        spark.sql(sql)
        n = spark.table(f"{k}.gold.{nome}").count()
        contagens.inserted += n
        print(f"gold.{nome}: {n} linhas")
    ind, td = f"{k}.gold.fct_indice_diario", f"{k}.gold.fct_tesouro_diario"
    regras = [
        dq.Regra("indice_chave_unica", "Uma linha por índice e pregão", "CRITICAL", ind,
                 f"SELECT indice, data_pregao, count(*) n FROM {ind} GROUP BY ALL HAVING n > 1", f"SELECT count(*) FROM {ind}"),
        dq.Regra("indice_com_nome", "Todos os índices carregados têm nome em config/datasets/mercado.yaml", "HIGH", ind,
                 f"SELECT DISTINCT indice FROM {ind} WHERE nome_indice IS NULL", f"SELECT count(DISTINCT indice) FROM {ind}"),
        dq.Regra("tesouro_indexador", "Todos os títulos têm indexador conhecido", "HIGH", td,
                 f"SELECT DISTINCT tipo_titulo FROM {td} WHERE indexador IS NULL", f"SELECT count(DISTINCT tipo_titulo) FROM {td}"),
        # o pregão mais recente do Ibovespa deve coincidir com o das cotações (fontes diferentes da mesma B3)
        dq.Regra("ibov_alinhado_cotahist", "Último pregão do IBOV até 3 dias diferente do último pregão do COTAHIST",
                 "INFO", ind,
                 f"""SELECT max(data_pregao) AS ibov, (SELECT max(data_pregao) FROM {k}.gold.fct_cotacao_diaria) AS cotahist
                     FROM {ind} WHERE indice = 'IBOV'
                     HAVING abs(datediff(ibov, cotahist)) > 3""", "SELECT 1"),
    ]
    resultados = dq.avaliar(spark, regras, amostra=10)
    dq.gravar(spark, k, p.run_id, resultados)
    for r in resultados:
        print(f"{r.regra.nome}: {'PASSED' if r.passou else 'FAILED'} ({r.falhados}/{r.avaliados}) {r.amostra[:5]}")
    if any(not r.passou and r.regra.severidade == "CRITICAL" for r in resultados):
        raise RuntimeError("regras críticas falharam na gold de mercado")
    control.concluir(spark, e, contagens)
except Exception as ex:
    control.falhar(spark, e, ex, contagens)
    raise
