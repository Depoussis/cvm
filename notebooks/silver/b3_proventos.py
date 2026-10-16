# Databricks notebook source
# MAGIC %md
# MAGIC # Silver · B3 proventos e eventos societários
# MAGIC A partir da carga bronze mais recente (cada carga traz o histórico completo):
# MAGIC - `b3_provento` (SCD1): dividendos, JCP e rendimentos por ação, com data com;
# MAGIC - `b3_evento_acao` (SCD1): desdobramentos, grupamentos e bonificações oficiais;
# MAGIC - `b3_empresa` (SCD1): CNPJ e número de ações ON/PN.
# MAGIC Números no formato brasileiro (`0,674`, `1.234,5`) e datas `dd/mm/aaaa`; o que não converte vai para a
# MAGIC quarentena e é contado na regra HIGH `formato_api`.

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

FONTE = "b3"
k = p.catalogo
hoje = date.today()
erros = {}


def num(c: str) -> str:
    """Número brasileiro em texto → DECIMAL ('1.234,56' → 1234.56)."""
    return f"try_cast(replace(replace(nullif(trim({c}), ''), '.', ''), ',', '.') AS DECIMAL(30, 11))"


def dt(c: str) -> str:
    return f"try_to_date(nullif(trim({c}), ''), 'dd/MM/yyyy')"


def ultima_carga(tabela: str) -> str:
    """Linhas da execução bronze mais recente da tabela (cada carga é um retrato completo)."""
    return (f"SELECT * FROM {k}.bronze.{tabela} WHERE _pipeline_run_id = "
            f"(SELECT max_by(_pipeline_run_id, _ingestion_timestamp) FROM {k}.bronze.{tabela})")


def carregar(entidade: str, destino: str, origem_sql: str, valido: str, select_sql: str, chaves: list[str],
             regras_extra: list | None = None) -> None:
    e = control.Execucao(k, p.run_id, "silver_b3_proventos", FONTE, entidade, "silver", p.run_mode)
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
        regras = [
            dq.Regra("chave_unica", f"Uma linha por {chaves}", "CRITICAL", f"{k}.silver.{destino}",
                     f"SELECT {', '.join(chaves)}, count(*) n FROM {k}.silver.{destino} GROUP BY ALL HAVING n > 1",
                     f"SELECT count(*) FROM {k}.silver.{destino}"),
            dq.Regra("formato_api", "Datas dd/mm/aaaa e números convertíveis", "HIGH", f"{k}.silver.{destino}",
                     "SELECT * FROM _pend WHERE NOT _valido", "SELECT count(*) FROM _pend"),
        ] + (regras_extra or [])
        resultados = dq.avaliar(spark, regras)
        dq.gravar(spark, k, p.run_id, resultados)
        falhas = [r.regra.nome for r in resultados if not r.passou]
        if any(not r.passou and r.regra.severidade == "CRITICAL" for r in resultados):
            raise RuntimeError(f"regras críticas falharam: {falhas}")
        control.concluir(spark, e, c)
        print(f"{destino}: lidos={c.read} chaves={n} novos={c.inserted} alterados={c.updated} "
              f"rejeitados={c.rejected} falhas={falhas}")
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        erros[entidade] = repr(ex)

# COMMAND ----------

if p.escolhida("proventos") or p.escolhida("b3_provento"):
    carregar(
        "b3_provento", "b3_provento", ultima_carga("b3_proventos_dinheiro"),
        f"{dt('data_com')} IS NOT NULL AND {num('valor')} IS NOT NULL AND nullif(trim(tipo_acao), '') IS NOT NULL",
        f"""
        SELECT emissor, upper(trim(tipo_acao)) AS tipo_acao, upper(trim(tipo_provento)) AS tipo_provento,
               {dt('data_com')} AS data_com, {dt('data_aprovacao')} AS data_aprovacao,
               {num('valor')} AS valor_por_acao, CAST({num('fecho_data_com')} AS DECIMAL(18, 6)) AS fecho_data_com,
               CAST({num('provento_pct_preco')} AS DOUBLE) AS provento_pct_preco,
               CAST({num('cotacao_por_acoes')} AS INT) AS cotacao_por_acoes, trim(nome_pregao_pedido) AS nome_pregao
        FROM _pend WHERE _valido
        -- a mesma deliberação pode aparecer repetida na fonte; data de aprovação diferente = outra linha
        QUALIFY row_number() OVER (PARTITION BY emissor, tipo_acao, tipo_provento, data_com, valor_por_acao
                                   ORDER BY data_aprovacao DESC NULLS LAST) = 1""",
        ["emissor", "tipo_acao", "tipo_provento", "data_com", "valor_por_acao"],
        [dq.Regra("valor_positivo", "Provento por ação maior que zero", "INFO", f"{k}.silver.b3_provento",
                  f"SELECT * FROM {k}.silver.b3_provento WHERE valor_por_acao <= 0",
                  f"SELECT count(*) FROM {k}.silver.b3_provento"),
         dq.Regra("provento_pct_suspeito", "Provento acima de 50 % do preço na data com", "INFO",
                  f"{k}.silver.b3_provento",
                  f"SELECT emissor, tipo_acao, data_com, valor_por_acao, fecho_data_com FROM {k}.silver.b3_provento "
                  f"WHERE provento_pct_preco > 50", f"SELECT count(*) FROM {k}.silver.b3_provento")])

if p.escolhida("proventos") or p.escolhida("b3_evento_acao"):
    carregar(
        "b3_evento_acao", "b3_evento_acao", ultima_carga("b3_eventos_acoes"),
        f"{dt('data_com')} IS NOT NULL AND {num('fator')} IS NOT NULL AND nullif(trim(isin), '') IS NOT NULL",
        f"""
        SELECT emissor, trim(isin) AS isin, upper(trim(tipo_evento)) AS tipo_evento, {dt('data_com')} AS data_com,
               max({dt('data_aprovacao')}) AS data_aprovacao, CAST(max({num('fator')}) AS DECIMAL(24, 11)) AS fator
        FROM _pend WHERE _valido GROUP BY 1, 2, 3, 4""",
        ["emissor", "isin", "tipo_evento", "data_com"])

if p.escolhida("proventos") or p.escolhida("b3_empresa"):
    carregar(
        "b3_empresa", "b3_empresa",
        f"""SELECT c.*, e.cnpj, e.razao_social, e.segmento AS segmento_lista, CAST(c._ingestion_timestamp AS DATE) AS dia
            FROM ({ultima_carga('b3_empresa_complemento')}) c
            LEFT JOIN ({ultima_carga('b3_empresas')}) e USING (emissor)""",
        f"{num('qtd_acoes_total')} IS NOT NULL",
        f"""
        SELECT emissor, nullif(regexp_replace(max(cnpj), '[^0-9]', ''), '') AS cnpj, max(razao_social) AS razao_social,
               max(trim(nome_pregao)) AS nome_pregao, max(codigo_cvm) AS codigo_cvm,
               max(coalesce(segmento, segmento_lista)) AS segmento,
               CAST(max({num('qtd_acoes_on')}) AS BIGINT) AS qtd_acoes_on,
               CAST(max({num('qtd_acoes_pn')}) AS BIGINT) AS qtd_acoes_pn,
               CAST(max({num('qtd_acoes_total')}) AS BIGINT) AS qtd_acoes_total, max(dia) AS data_referencia
        FROM _pend WHERE _valido GROUP BY emissor""",
        ["emissor"])

if erros:
    raise RuntimeError(f"falharam {len(erros)} entidades: {erros}")
