# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze · B3 (COTAHIST)
# MAGIC Cotações históricas da B3, ficheiros de largura fixa (`config/datasets/b3.yaml`).
# MAGIC - `backfill`: ficheiros anuais desde `inicio_backfill`; `incremental`: diários dos últimos `revisao_dias`;
# MAGIC   `reprocess`: anuais entre `data_inicio` e `data_fim` (descarrega de novo mesmo sem alteração).
# MAGIC - `HEAD` compara ETag/Last-Modified com a última versão registada; só descarrega o que mudou. Dia sem pregão = 404.
# MAGIC - O ZIP original vai para o volume `ops.raw`, o TXT é extraído ao lado; cabeçalho e trailer são validados
# MAGIC   (total de registos). Ficheiro truncado → quarentena e falha.
# MAGIC - A bronze guarda os registos do mercado à vista (`mercados_bronze`), campos como texto.

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
import os
from datetime import date

from pyspark.sql import functions as F

from src.audit import control
from src.bronze import writer
from src.common import raw_store
from src.common.config import carregar_yaml
from src.common.http import ClienteHttp
from src.ingestion.b3 import cotahist
from src.ingestion.cvm.files import mudou

logging.basicConfig(level=logging.INFO)
FONTE, ENTIDADE = "b3", "cotahist"
cfg = carregar_yaml("datasets/b3.yaml")["cotahist"]
cliente = ClienteHttp(carregar_yaml("sources/bcb.yaml")["http"] | {"pausa_entre_pedidos_s": 0.5, "timeout_s": 600})
hoje = date.today()
tabela = f"{p.catalogo}.bronze.{cfg['tabela_bronze']}"  # criada por sql/schemas/12_b3_bronze.sql (apply_sql)

# COMMAND ----------

def ler_linhas(caminho_txt: str):
    """Uma coluna `linha` por registo. Sem aspas nem separador: cada linha de 245 posições fica inteira."""
    return (spark.read.option("encoding", "ISO-8859-1").option("sep", "\u0001").option("quote", "\u0000")
            .option("header", False).schema("linha STRING").csv(caminho_txt))


def processar(url: str, periodo: str, c: control.Contagens, ja: set[str], forcar: bool) -> str:
    h = cliente.head(url)
    if h.status == 404:
        return "NAO_PUBLICADO"
    if not forcar and not mudou(h.etag, h.last_modified, writer.ultimo_registo(spark, p.catalogo, url)):
        return "SEM_ALTERACAO"
    r = cliente.get(url)
    nome_remoto = url.rsplit("/", 1)[-1]
    caminho = raw_store.caminho_raw(p.catalogo, FONTE, ENTIDADE, hoje, p.run_id, nome_remoto)
    raw_store.gravar(caminho, r.conteudo)
    hash_ = raw_store.sha256(r.conteudo)
    origem = writer.Origem(FONTE, ENTIDADE, url, caminho, hash_, len(r.conteudo), None, None,
                           r.etag or h.etag, r.last_modified or h.last_modified)
    if hash_ in ja:
        writer.registar_ficheiros(spark, p.catalogo, [writer.linha_registo(
            origem, p.run_id, "DUPLICATE", "conteúdo idêntico a uma versão já processada", periodo)])
        return "DUPLICATE"

    pasta = caminho.rsplit("/", 1)[0] + "/extraidos"
    os.makedirs(pasta, exist_ok=True)
    temporario = f"{pasta}/.parcial"
    with open(temporario, "wb") as destino:
        nome_txt = cotahist.extrair_txt(r.conteudo, destino)
    caminho_txt = f"{pasta}/{nome_txt}"
    os.replace(temporario, caminho_txt)

    linhas = ler_linhas(caminho_txt).withColumn("tipreg", F.substring("linha", 1, 2))
    envelope = {x.tipreg: x.linha for x in linhas.where("tipreg IN ('00', '99')").collect()}
    detalhes = linhas.where("tipreg = '01'").count()
    problemas = cotahist.validar_envelope(envelope.get("00", ""), envelope.get("99", ""), detalhes)
    if problemas:
        q = f"/Volumes/{p.catalogo}/ops/quarantine/{FONTE}/{ENTIDADE}/ingestion_date={hoje}/{p.run_id}"
        raw_store.gravar(f"{q}/{nome_remoto}", r.conteudo)
        raw_store.gravar(f"{q}/{nome_remoto}.motivo.json",
                         json.dumps({"motivo": problemas, "url": url}, ensure_ascii=False).encode())
        writer.registar_ficheiros(spark, p.catalogo, [writer.linha_registo(
            origem, p.run_id, "QUARANTINED", "; ".join(problemas), periodo)])
        raise ValueError(f"{nome_remoto}: {problemas}")

    mercados = ", ".join(f"'{m}'" for m in cfg["mercados_bronze"])
    df = (linhas.where(f"tipreg = '01' AND substring(linha, 25, 3) IN ({mercados})")
          .selectExpr(*cotahist.expressoes_spark("linha"), "sha2(linha, 256) AS _record_hash")
          .withColumn("_source_file_name", F.lit(nome_txt))
          .withColumn("_reference_period", F.lit(periodo))
          .withColumn("_source_system", F.lit(FONTE))
          .withColumn("_source_entity", F.lit(ENTIDADE))
          .withColumn("_source_url", F.lit(url))
          .withColumn("_source_file_path", F.lit(caminho))
          .withColumn("_file_hash", F.lit(hash_))
          .withColumn("_ingestion_timestamp", F.current_timestamp())
          .withColumn("_pipeline_run_id", F.lit(p.run_id)))
    df.select(*spark.table(tabela).columns).write.mode("append").saveAsTable(tabela)
    n = spark.table(tabela).where(F.col("_file_hash") == hash_).where(F.col("_pipeline_run_id") == p.run_id).count()
    c.read += detalhes
    c.inserted += n
    print(f"  {nome_txt}: {detalhes} cotações no ficheiro, {n} do mercado à vista na bronze")
    writer.registar_ficheiros(spark, p.catalogo, [writer.linha_registo(origem, p.run_id, "PROCESSED", None, periodo)])
    return "PROCESSED"

# COMMAND ----------

erros = {}
if p.escolhida(ENTIDADE):
    lista = cotahist.alvos(p.run_mode, cfg, hoje, p.data_inicio, p.data_fim)
    e = control.Execucao(p.catalogo, p.run_id, "bronze_b3", FONTE, ENTIDADE, "bronze", p.run_mode,
                         lista[0][1] if lista else None, lista[-1][1] if lista else None, {"ficheiros": len(lista)})
    control.iniciar(spark, e)
    c = control.Contagens()
    estados = {}
    try:
        ja = writer.hashes_processados(spark, p.catalogo, FONTE, ENTIDADE)
        for url, periodo in lista:
            estado = processar(url, periodo, c, ja, forcar=p.run_mode == "reprocess")
            estados[estado] = estados.get(estado, 0) + 1
            print(f"{periodo}: {estado}")
        e.parameters["estados_ficheiros"] = estados
        control.concluir(spark, e, c)  # o watermark (último pregão) é confirmado pela silver
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        erros[ENTIDADE] = repr(ex)

if erros:
    raise RuntimeError(f"falharam {len(erros)} entidades: {erros}")
