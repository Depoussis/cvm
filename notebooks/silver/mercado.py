# Databricks notebook source
# MAGIC %md
# MAGIC # Silver · Referências de mercado
# MAGIC A partir da carga bronze mais recente de cada tabela (SCD1):
# MAGIC - `b3_indice_diario`: fecho diário por índice (data = ano/mês/dia da matriz da B3);
# MAGIC - `tesouro_preco_taxa`: taxas e preços por título e data base.
# MAGIC Números no formato brasileiro e datas `dd/mm/aaaa`; o que não converte vai para a quarentena (regra HIGH
# MAGIC `formato_fonte`). O watermark (data mais recente) só avança depois das regras críticas.

# COMMAND ----------

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd().parents[1]))

from src.common import notebook

notebook.declarar(dbutils)
p = notebook.ler(dbutils)
print(p)

# COMMAND ----------

from datetime import date

from src.audit import control
from src.quality import rules as dq
from src.scd.merge_sql import expr_hash, merge_scd1
from src.silver.common import caminho_quarentena, executar_merge

FONTE = "mercado"
k = p.catalogo
hoje = date.today()
erros = {}


def num(c: str, tipo: str = "DECIMAL(18, 4)") -> str:
    """'1.234,56' → 1234.56 (os PU do Tesouro vêm sem separador de milhar: '2143,63')."""
    return f"try_cast(replace(replace(nullif(trim({c}), ''), '.', ''), ',', '.') AS {tipo})"


def dt(c: str) -> str:
    return f"try_to_date(nullif(trim({c}), ''), 'dd/MM/yyyy')"


def ultima_carga(tabela: str) -> str:
    return (f"SELECT * FROM {k}.bronze.{tabela} WHERE _pipeline_run_id = "
            f"(SELECT max_by(_pipeline_run_id, _ingestion_timestamp) FROM {k}.bronze.{tabela})")


def carregar(entidade: str, destino: str, origem_sql: str, valido: str, select_sql: str, chaves: list[str],
             coluna_data: str, regras_extra: list) -> None:
    e = control.Execucao(k, p.run_id, "silver_mercado", FONTE, entidade, "silver", p.run_mode)
    control.iniciar(spark, e)
    c = control.Contagens()
    try:
        spark.sql(f"SELECT *, coalesce(({valido}), false) AS _valido FROM ({origem_sql})").createOrReplaceTempView("_pend")
        c.read = spark.table("_pend").count()
        invalidos = spark.table("_pend").where("NOT _valido").drop("_valido")
        c.rejected = invalidos.count()
        if c.rejected:
            invalidos.write.mode("append").json(caminho_quarentena(k, FONTE, entidade, hoje, p.run_id))
        df = spark.sql(select_sql)
        atributos = [x for x in df.columns if x not in chaves]
        (df.selectExpr("*", f"{expr_hash(atributos)} AS record_hash", f"'{p.run_id}' AS _pipeline_run_id")
           .createOrReplaceTempView("_src"))
        n = spark.table("_src").count()
        c.inserted, c.updated = executar_merge(spark, merge_scd1(f"{k}.silver.{destino}", "_src", chaves, atributos))
        c.unchanged = n - c.inserted - c.updated
        tabela = f"{k}.silver.{destino}"
        regras = [
            dq.Regra("chave_unica", f"Uma linha por {chaves}", "CRITICAL", tabela,
                     f"SELECT {', '.join(chaves)}, count(*) n FROM {tabela} GROUP BY ALL HAVING n > 1",
                     f"SELECT count(*) FROM {tabela}"),
            dq.Regra("formato_fonte", "Datas dd/mm/aaaa e números convertíveis", "HIGH", tabela,
                     "SELECT * FROM _pend WHERE NOT _valido", "SELECT count(*) FROM _pend"),
        ] + regras_extra
        resultados = dq.avaliar(spark, regras)
        dq.gravar(spark, k, p.run_id, resultados)
        falhas = [r.regra.nome for r in resultados if not r.passou]
        if any(not r.passou and r.regra.severidade == "CRITICAL" for r in resultados):
            raise RuntimeError(f"regras críticas falharam: {falhas}")
        maximo = spark.sql(f"SELECT max({coluna_data}) FROM {tabela}").collect()[0][0]
        if maximo:
            control.confirmar_watermark(spark, e, "reference_date", maximo.isoformat(), None)
        control.concluir(spark, e, c)
        print(f"{destino}: lidos={c.read} chaves={n} novos={c.inserted} alterados={c.updated} "
              f"rejeitados={c.rejected} watermark={maximo} falhas={falhas}")
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        erros[entidade] = repr(ex)

# COMMAND ----------

if p.escolhida("indices_b3"):
    data_sql = "try_cast(make_date(int(ano), int(mes), int(dia)) AS DATE)"
    carregar(
        "indices_b3", "b3_indice_diario", ultima_carga("b3_indice_dia"),
        f"{data_sql} IS NOT NULL AND {num('valor')} > 0",
        f"""SELECT upper(trim(indice)) AS indice, {data_sql} AS data_pregao,
                   CAST({num('valor')} AS DECIMAL(18, 2)) AS fechamento
            FROM _pend WHERE _valido
            QUALIFY row_number() OVER (PARTITION BY upper(trim(indice)), {data_sql} ORDER BY _ingestion_timestamp DESC) = 1""",
        ["indice", "data_pregao"], "data_pregao",
        [dq.Regra("salto_indice", "Variação diária de um índice acima de 15 % (valor errado na fonte?)", "INFO",
                  f"{k}.silver.b3_indice_diario",
                  f"""SELECT indice, data_pregao, fechamento, anterior FROM (
                        SELECT indice, data_pregao, fechamento,
                               lag(fechamento) OVER (PARTITION BY indice ORDER BY data_pregao) AS anterior
                        FROM {k}.silver.b3_indice_diario)
                      WHERE abs(fechamento / anterior - 1) > 0.15""",
                  f"SELECT count(*) FROM {k}.silver.b3_indice_diario")])

if p.escolhida("tesouro_direto"):
    carregar(
        "tesouro_direto", "tesouro_preco_taxa", ultima_carga("tesouro_preco_taxa"),
        f"{dt('data_base')} IS NOT NULL AND {dt('data_vencimento')} IS NOT NULL AND "
        f"nullif(trim(tipo_titulo), '') IS NOT NULL AND {num('pu_base')} >= 0",
        f"""SELECT trim(tipo_titulo) AS tipo_titulo, {dt('data_vencimento')} AS data_vencimento,
                   {dt('data_base')} AS data_base,
                   CAST({num('taxa_compra')} AS DECIMAL(9, 4)) AS taxa_compra,
                   CAST({num('taxa_venda')} AS DECIMAL(9, 4)) AS taxa_venda,
                   CAST(nullif({num('pu_compra')}, 0) AS DECIMAL(18, 2)) AS pu_compra,
                   CAST(nullif({num('pu_venda')}, 0) AS DECIMAL(18, 2)) AS pu_venda,
                   CAST(nullif({num('pu_base')}, 0) AS DECIMAL(18, 2)) AS pu_base
            FROM _pend WHERE _valido
            QUALIFY row_number() OVER (PARTITION BY trim(tipo_titulo), {dt('data_vencimento')}, {dt('data_base')}
                                       ORDER BY _ingestion_timestamp DESC) = 1""",
        ["tipo_titulo", "data_vencimento", "data_base"], "data_base",
        # a fonte tem preços a zero em alguns dias antigos (ex.: Prefixado com Juros Semestrais 2021, jan-mar/2010):
        # ficam sem preço (NULL), com a taxa, e contados numa regra INFO
        [dq.Regra("pu_nao_negativo", "Preço unitário base não negativo", "HIGH", f"{k}.silver.tesouro_preco_taxa",
                  f"SELECT * FROM {k}.silver.tesouro_preco_taxa WHERE pu_base < 0",
                  f"SELECT count(*) FROM {k}.silver.tesouro_preco_taxa"),
         dq.Regra("pu_sem_valor", "Dias em que a fonte publicou o preço a zero", "INFO", f"{k}.silver.tesouro_preco_taxa",
                  f"SELECT tipo_titulo, data_vencimento, data_base FROM {k}.silver.tesouro_preco_taxa WHERE pu_base IS NULL",
                  f"SELECT count(*) FROM {k}.silver.tesouro_preco_taxa")])

if erros:
    raise RuntimeError(f"falharam {len(erros)} entidades: {erros}")
