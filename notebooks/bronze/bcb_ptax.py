# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze · BCB PTAX
# MAGIC Descarrega o catálogo de moedas e as cotações (todos os boletins) do serviço OData PTAX, guarda os
# MAGIC originais no volume `ops.raw` e acrescenta os registos a `bronze.bcb_ptax_moedas` e `bronze.bcb_ptax_cotacoes`.
# MAGIC Entidades: `moedas` e `cotacao_<MOEDA>` (ex.: `cotacao_USD`). Mesmos modos de execução da bronze SGS.

# COMMAND ----------

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd().parents[1]))

from src.common import notebook

notebook.declarar(dbutils)
p = notebook.ler(dbutils)
print(p)

# COMMAND ----------

import logging
from datetime import date

from src.audit import control
from src.bronze import writer
from src.common import janela, raw_store
from src.common.config import carregar_yaml
from src.common.http import ClienteHttp
from src.ingestion.bcb_ptax import client as ptax

logging.basicConfig(level=logging.INFO)
FONTE = "bcb_ptax"
fonte = carregar_yaml("sources/bcb.yaml")
cfg = fonte["bcb_ptax"]
cliente = ClienteHttp(fonte["http"])
hoje = date.today()
erros = {}


def gravar_pagina(pg, nome_ficheiro, negocio, tabela, ja_processados, c):
    """Guarda o original, deteta duplicados e devolve (linhas bronze, linha do registo de ficheiros)."""
    h = raw_store.sha256(pg.conteudo)
    caminho = raw_store.caminho_raw(p.catalogo, FONTE, pg.entidade, hoje, p.run_id, nome_ficheiro)
    raw_store.gravar(caminho, pg.conteudo)
    origem = writer.Origem(FONTE, pg.entidade, pg.url, caminho, h, len(pg.conteudo), pg.inicio, pg.fim)
    c.read += len(negocio)
    periodo = f"{pg.inicio}/{pg.fim}" if pg.inicio else None
    if h in ja_processados:
        c.unchanged += len(negocio)
        return [], writer.linha_registo(origem, p.run_id, "DUPLICATE", "payload idêntico a um já processado", periodo)
    return writer.linhas_bronze(negocio, origem, p.run_id), writer.linha_registo(origem, p.run_id, "PROCESSED", None, periodo)

# COMMAND ----------

# MAGIC %md ## Moedas

# COMMAND ----------

moedas_oficiais = set()
if p.escolhida("moedas"):
    e = control.Execucao(p.catalogo, p.run_id, "bronze_bcb_ptax", FONTE, "moedas", "bronze", p.run_mode)
    control.iniciar(spark, e)
    c = control.Contagens()
    try:
        pg = ptax.extrair_moedas(cliente, cfg["url_moedas"])
        moedas_oficiais = {m["simbolo"] for m in pg.registos}
        negocio = [{"simbolo": m["simbolo"], "nome_formatado": m["nomeFormatado"], "tipo_moeda": m["tipoMoeda"]}
                   for m in pg.registos]
        linhas, reg = gravar_pagina(pg, "moedas.json", negocio, None,
                                    writer.hashes_processados(spark, p.catalogo, FONTE, "moedas"), c)
        c.inserted = writer.append(spark, f"{p.catalogo}.bronze.bcb_ptax_moedas", linhas)
        writer.registar_ficheiros(spark, p.catalogo, [reg])
        control.concluir(spark, e, c)
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        erros["moedas"] = repr(ex)
else:
    moedas_oficiais = {m["simbolo"] for m in ptax.extrair_moedas(cliente, cfg["url_moedas"]).registos}

desconhecidas = set(cfg["moedas"]) - moedas_oficiais
if moedas_oficiais and desconhecidas:
    raise ValueError(f"moedas configuradas que o BCB não publica: {sorted(desconhecidas)}")

# COMMAND ----------

# MAGIC %md ## Cotações

# COMMAND ----------

tabela = f"{p.catalogo}.bronze.bcb_ptax_cotacoes"
for moeda in cfg["moedas"]:
    entidade = f"cotacao_{moeda}"
    if not p.escolhida(entidade):
        continue
    wm = control.ler_watermark(spark, p.catalogo, FONTE, entidade)
    inicio, fim = janela.intervalo(p.run_mode, date.fromisoformat(str(cfg["inicio_backfill"])), cfg["revisao_dias"], hoje,
                                   date.fromisoformat(wm["watermark_value"]) if wm else None, p.data_inicio, p.data_fim)
    e = control.Execucao(p.catalogo, p.run_id, "bronze_bcb_ptax", FONTE, entidade, "bronze", p.run_mode,
                         inicio.isoformat(), fim.isoformat(), {"moeda": moeda})
    control.iniciar(spark, e)
    c = control.Contagens()
    try:
        ja = writer.hashes_processados(spark, p.catalogo, FONTE, entidade)
        linhas, registos = [], []
        for pg in ptax.extrair_cotacoes(cliente, cfg["url_cotacoes"], moeda, inicio, fim, cfg["janela_max_dias"]):
            negocio = [{"moeda": moeda, "paridade_compra": r["paridadeCompra"], "paridade_venda": r["paridadeVenda"],
                        "cotacao_compra": r["cotacaoCompra"], "cotacao_venda": r["cotacaoVenda"],
                        "data_hora_cotacao": r["dataHoraCotacao"], "tipo_boletim": r["tipoBoletim"]}
                       for r in pg.registos]
            l, reg = gravar_pagina(pg, f"ptax_{moeda}_{pg.inicio:%Y%m%d}_{pg.fim:%Y%m%d}.json", negocio, tabela, ja, c)
            linhas += l
            registos.append(reg)
        c.inserted = writer.append(spark, tabela, linhas)
        writer.registar_ficheiros(spark, p.catalogo, registos)
        control.concluir(spark, e, c)
        print(f"{entidade}: {inicio}..{fim} lidos={c.read} bronze={c.inserted} duplicados={c.unchanged}")
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        erros[entidade] = repr(ex)

if erros:
    raise RuntimeError(f"falharam {len(erros)} entidades: {erros}")

# COMMAND ----------

display(spark.sql(f"""
  SELECT entity_name, execution_status, records_read, records_inserted, records_unchanged, watermark_start, watermark_end
  FROM {p.catalogo}.control.pipeline_execution WHERE pipeline_run_id = '{p.run_id}' AND layer = 'bronze'
  ORDER BY entity_name"""))
