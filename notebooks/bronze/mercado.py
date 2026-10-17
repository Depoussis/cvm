# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze · Referências de mercado (índices B3 e Tesouro Direto)
# MAGIC Fontes em `config/datasets/mercado.yaml`, funções em `src/ingestion/mercado.py`.
# MAGIC - **indices_b3**: um pedido por índice e ano (matriz dia x mês). Primeira carga ou `backfill`: desde
# MAGIC   `inicio_backfill`; incremental: os últimos `anos_incremental` anos. As respostas vão para um JSON Lines no
# MAGIC   volume `ops.raw`.
# MAGIC - **tesouro_direto**: o CSV completo vai sempre para o volume; para a bronze vão as linhas com data base a partir
# MAGIC   do watermark menos `revisao_dias` (tudo na primeira carga ou em `backfill`). Se o ficheiro for igual a um já
# MAGIC   processado (mesmo hash), não grava nada.

# COMMAND ----------

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd().parents[1]))

from src.common import notebook

notebook.declarar(dbutils)
p = notebook.ler(dbutils)
print(p)

# COMMAND ----------

import json
import logging
from datetime import date, timedelta

from src.audit import control
from src.bronze import writer
from src.common import raw_store
from src.common.config import carregar_yaml
from src.common.http import ClienteHttp
from src.ingestion import mercado as m

logging.basicConfig(level=logging.INFO)
FONTE = "mercado"
cfg = carregar_yaml("datasets/mercado.yaml")
http = carregar_yaml("sources/bcb.yaml")["http"]
k = p.catalogo
hoje = date.today()
erros = {}

# COMMAND ----------

if p.escolhida("indices_b3"):
    ci = cfg["indices_b3"]
    e = control.Execucao(k, p.run_id, "bronze_mercado", FONTE, "indices_b3", "bronze", p.run_mode)
    control.iniciar(spark, e)
    c = control.Contagens()
    try:
        cliente = ClienteHttp(http | {"pausa_entre_pedidos_s": ci["pausa_entre_pedidos_s"], "timeout_s": 60})
        wm = control.ler_watermark(spark, k, FONTE, "indices_b3")
        anos = m.anos_a_pedir(p.run_mode, ci["inicio_backfill"], ci["anos_incremental"], hoje,
                              date.fromisoformat(wm["watermark_value"]).year if wm else None)
        respostas, por_url = [], {}
        for indice in ci["indices"]:
            for ano in anos:
                url = m.url_indice(ci["url"], indice, ano)
                r = cliente.get(url)
                respostas.append({"url": url, "corpo": r.conteudo.decode("utf-8", "replace")})
                por_url[url] = m.linhas_indice(json.loads(r.conteudo), indice, ano)
        conteudo = "\n".join(json.dumps(x, ensure_ascii=False) for x in respostas).encode()
        caminho = raw_store.caminho_raw(k, FONTE, "indices_b3", hoje, p.run_id, "respostas.jsonl")
        raw_store.gravar(caminho, conteudo)
        h = raw_store.sha256(conteudo)
        bronze = []
        for url, linhas in por_url.items():
            origem = writer.Origem(FONTE, "indices_b3", url, caminho, h, len(conteudo), None, None)
            bronze += writer.linhas_bronze(linhas, origem, p.run_id)
        c.read = c.inserted = writer.append(spark, f"{k}.bronze.{ci['tabela_bronze']}", bronze)
        writer.registar_ficheiros(spark, k, [writer.linha_registo(
            writer.Origem(FONTE, "indices_b3", ci["url"], caminho, h, len(conteudo), None, None), p.run_id,
            "PROCESSED", f"{len(respostas)} pedidos, anos {anos[0]}-{anos[-1]}", None)])
        e.parameters.update({"indices": list(ci["indices"]), "anos": anos})
        control.concluir(spark, e, c)
        print(f"indices_b3: {len(respostas)} pedidos ({anos[0]}-{anos[-1]}), {c.inserted} linhas na bronze")
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        erros["indices_b3"] = repr(ex)

# COMMAND ----------

if p.escolhida("tesouro_direto"):
    ct = cfg["tesouro_direto"]
    e = control.Execucao(k, p.run_id, "bronze_mercado", FONTE, "tesouro_direto", "bronze", p.run_mode)
    control.iniciar(spark, e)
    c = control.Contagens()
    try:
        r = ClienteHttp(http | {"timeout_s": 180}).get(ct["url"])
        h = raw_store.sha256(r.conteudo)
        if p.run_mode != "backfill" and h in writer.hashes_processados(spark, k, FONTE, "tesouro_direto"):
            print("tesouro_direto: ficheiro igual a um já processado, nada a fazer")
        else:
            caminho = raw_store.caminho_raw(k, FONTE, "tesouro_direto", hoje, p.run_id, "PrecoTaxaTesouroDireto.csv")
            raw_store.gravar(caminho, r.conteudo)
            wm = control.ler_watermark(spark, k, FONTE, "tesouro_direto")
            desde = (date.fromisoformat(wm["watermark_value"]) - timedelta(days=ct["revisao_dias"])
                     if wm and p.run_mode != "backfill" else None)
            linhas = m.linhas_tesouro(r.conteudo, desde)
            origem = writer.Origem(FONTE, "tesouro_direto", ct["url"], caminho, h, len(r.conteudo), desde, hoje)
            c.read = c.inserted = writer.append(spark, f"{k}.bronze.{ct['tabela_bronze']}",
                                                writer.linhas_bronze(linhas, origem, p.run_id))
            writer.registar_ficheiros(spark, k, [writer.linha_registo(
                origem, p.run_id, "PROCESSED", f"{len(linhas)} linhas desde {desde or 'o início'}", None)])
            print(f"tesouro_direto: {len(r.conteudo) / 1e6:.1f} MB, {c.inserted} linhas na bronze (desde {desde})")
        control.concluir(spark, e, c)
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        erros["tesouro_direto"] = repr(ex)

if erros:
    raise RuntimeError(f"falharam {len(erros)} entidades: {erros}")
