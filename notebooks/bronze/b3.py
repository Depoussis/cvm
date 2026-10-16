# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze · B3 (COTAHIST)
# MAGIC Cotações históricas da B3, ficheiros de largura fixa (`config/datasets/b3.yaml`).
# MAGIC - `backfill`: ficheiros anuais desde `inicio_backfill`; `incremental`: diários dos últimos `revisao_dias`;
# MAGIC   `reprocess`: anuais entre `data_inicio` e `data_fim` (descarrega de novo mesmo sem alteração).
# MAGIC - `HEAD` compara ETag/Last-Modified com a última versão registada; só descarrega o que mudou. Dia sem pregão = 404.
# MAGIC - O ZIP original vai para o volume `ops.raw`, o TXT é extraído ao lado; cabeçalho e trailer são validados
# MAGIC   (total de registos). Ficheiro truncado → quarentena e falha. Ficheiro válido → registo `RECEIVED`.
# MAGIC - **Auto Loader** (stream `availableNow`) carrega os TXT novos na bronze: só o mercado à vista
# MAGIC   (`mercados_bronze`), campos como texto. Ver docs/streaming.md.

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

# MAGIC %md ## 1. Download: ZIP para o raw, TXT extraído e validado, registo `RECEIVED`

# COMMAND ----------

def aterrar(url: str, periodo: str, c: control.Contagens, ja: set[str], forcar: bool) -> str:
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
    # extrai para um nome fora do padrão *.TXT, para o Auto Loader nunca ver um ficheiro a meio
    temporario = f"{pasta}/.parcial"
    with open(temporario, "wb") as destino:
        nome_txt = cotahist.extrair_txt(r.conteudo, destino)
    with open(temporario, "rb") as f:
        cabecalho, trailer, detalhes = cotahist.ler_envelope(f)
    problemas = cotahist.validar_envelope(cabecalho, trailer, detalhes)
    if problemas:
        os.remove(temporario)
        q = f"/Volumes/{p.catalogo}/ops/quarantine/{FONTE}/{ENTIDADE}/ingestion_date={hoje}/{p.run_id}"
        raw_store.gravar(f"{q}/{nome_remoto}", r.conteudo)
        raw_store.gravar(f"{q}/{nome_remoto}.motivo.json",
                         json.dumps({"motivo": problemas, "url": url}, ensure_ascii=False).encode())
        writer.registar_ficheiros(spark, p.catalogo, [writer.linha_registo(
            origem, p.run_id, "QUARANTINED", "; ".join(problemas), periodo)])
        raise ValueError(f"{nome_remoto}: {problemas}")
    # o registo vem antes de o TXT aparecer: o Auto Loader só carrega ficheiros com registo RECEIVED
    writer.registar_ficheiros(spark, p.catalogo, [writer.linha_registo(
        origem, p.run_id, "RECEIVED", f"{detalhes} cotações; aguarda o Auto Loader", periodo)])
    os.replace(temporario, f"{pasta}/{nome_txt}")
    c.read += detalhes
    print(f"  {nome_txt}: {detalhes} cotações, envelope OK")
    return "RECEIVED"

# COMMAND ----------

# MAGIC %md ## 2. Auto Loader: TXT novos no raw → bronze
# MAGIC Stream `availableNow` com checkpoint: cada TXT é lido uma única vez, mesmo entre execuções. Cada lote junta
# MAGIC os ficheiros ao seu registo `RECEIVED` (pela pasta da execução e nome), escreve na bronze de forma idempotente
# MAGIC (`txnAppId`/`txnVersion`: um lote repetido depois de uma falha não duplica linhas) e marca-os `PROCESSED`.
# MAGIC TXT sem registo `RECEIVED` (ex.: carregados antes desta versão) são ignorados.

# COMMAND ----------

RAIZ = f"/Volumes/{p.catalogo}/ops/raw/{FONTE}/{ENTIDADE}/"
CHECKPOINT = f"/Volumes/{p.catalogo}/ops/checkpoints/bronze_b3_cotahist"
MERCADOS = ", ".join(f"'{m}'" for m in cfg["mercados_bronze"])
COLUNAS_BRONZE = spark.table(tabela).columns


def checkpoint_existe() -> bool:
    try:
        return len(dbutils.fs.ls(CHECKPOINT)) > 0
    except Exception:
        return False


def carregar_lote(lote, lote_id: int) -> None:
    s = lote.sparkSession
    registos = s.sql(f"""
        SELECT file_id, source_url, stored_path, file_hash_sha256, reference_period,
               {cotahist.chave_ficheiro_sql('stored_path')} AS chave
        FROM {p.catalogo}.control.source_file_registry
        WHERE source_system = '{FONTE}' AND entity_name = '{ENTIDADE}' AND processing_status = 'RECEIVED'""")
    dados = (lote.withColumn("chave", F.expr(cotahist.chave_ficheiro_sql("ficheiro")))
             .join(F.broadcast(registos), "chave"))
    ficheiros = [r.file_id for r in dados.select("file_id").distinct().collect()]
    lidos = lote.select("ficheiro").distinct().count()
    if not ficheiros:
        print(f"lote {lote_id}: {lidos} ficheiros sem registo RECEIVED, ignorados")
        return
    linhas = (dados.where(f"substring(linha, 1, 2) = '01' AND substring(linha, 25, 3) IN ({MERCADOS})")
              .selectExpr(*cotahist.expressoes_spark("linha"), "sha2(linha, 256) AS _record_hash",
                          "regexp_extract(ficheiro, '[^/]+$', 0) AS _source_file_name",
                          "reference_period AS _reference_period", f"'{FONTE}' AS _source_system",
                          f"'{ENTIDADE}' AS _source_entity", "source_url AS _source_url",
                          "stored_path AS _source_file_path", "file_hash_sha256 AS _file_hash",
                          "current_timestamp() AS _ingestion_timestamp", f"'{p.run_id}' AS _pipeline_run_id"))
    (linhas.select(*COLUNAS_BRONZE).write.mode("append")
     .option("txnAppId", "bronze_b3_cotahist").option("txnVersion", lote_id).saveAsTable(tabela))
    ids = ", ".join(f"'{f}'" for f in ficheiros)
    n = s.sql(f"SELECT count(*) FROM {tabela} WHERE _pipeline_run_id = '{p.run_id}' AND _file_hash IN "
              f"(SELECT file_hash_sha256 FROM {p.catalogo}.control.source_file_registry WHERE file_id IN ({ids}))"
              ).first()[0]
    s.sql(f"""UPDATE {p.catalogo}.control.source_file_registry
              SET processing_status = 'PROCESSED', status_detail = 'carregado pelo Auto Loader (lote {lote_id})',
                  pipeline_run_id = '{p.run_id}', updated_at = current_timestamp()
              WHERE file_id IN ({ids})""")
    # (no serverless o foreachBatch corre noutro processo: variáveis do notebook alteradas aqui não voltam;
    #  as contagens da execução leem-se depois no registo e na bronze)
    print(f"lote {lote_id}: {len(ficheiros)} de {lidos} ficheiros carregados, {n} linhas do mercado à vista")


def auto_loader() -> None:
    """Corre o stream até esgotar os ficheiros novos."""
    # Ambiente com a bronze já carregada pelo método anterior: na primeira execução ignora os TXT existentes
    # (já estão na bronze). Num ambiente novo (bronze vazia), lê tudo o que houver.
    existentes = "true" if checkpoint_existe() or spark.table(tabela).limit(1).count() == 0 else "false"
    q = (spark.readStream.format("cloudFiles")
         .option("cloudFiles.format", "csv").option("cloudFiles.includeExistingFiles", existentes)
         .option("pathGlobFilter", "*.TXT")
         .option("encoding", "ISO-8859-1").option("sep", "\u0001").option("quote", "\u0000")
         .option("header", "false").schema("linha STRING")
         .load(RAIZ)
         .select("linha", F.col("_metadata.file_path").alias("ficheiro"))
         .writeStream.foreachBatch(carregar_lote)
         .option("checkpointLocation", CHECKPOINT).trigger(availableNow=True)
         .queryName("bronze_b3_cotahist").start())
    q.awaitTermination()

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
        auto_loader()  # recupera ficheiros RECEIVED de uma execução anterior que falhou (e inicia o checkpoint)
        ja = writer.hashes_processados(spark, p.catalogo, FONTE, ENTIDADE)
        for url, periodo in lista:
            estado = aterrar(url, periodo, c, ja, forcar=p.run_mode == "reprocess")
            estados[estado] = estados.get(estado, 0) + 1
            print(f"{periodo}: {estado}")
        auto_loader()
        carregados = spark.sql(f"""
            SELECT count(*) AS ficheiros,
                   (SELECT count(*) FROM {tabela} WHERE _pipeline_run_id = '{p.run_id}') AS linhas
            FROM {p.catalogo}.control.source_file_registry
            WHERE source_system = '{FONTE}' AND entity_name = '{ENTIDADE}' AND pipeline_run_id = '{p.run_id}'
              AND processing_status = 'PROCESSED' AND status_detail LIKE 'carregado pelo Auto Loader%'""").first()
        c.inserted = carregados.linhas
        e.parameters["estados_ficheiros"] = estados
        e.parameters["auto_loader"] = {"ficheiros": carregados.ficheiros, "linhas_bronze": carregados.linhas}
        print(f"Auto Loader: {e.parameters['auto_loader']}")
        pendentes = spark.sql(f"""SELECT count(*) FROM {p.catalogo}.control.source_file_registry
                                  WHERE source_system = '{FONTE}' AND entity_name = '{ENTIDADE}'
                                    AND processing_status = 'RECEIVED'""").first()[0]
        if pendentes:
            raise RuntimeError(f"{pendentes} ficheiros continuam RECEIVED depois do Auto Loader")
        control.concluir(spark, e, c)  # o watermark (último pregão) é confirmado pela silver
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        erros[ENTIDADE] = repr(ex)

if erros:
    raise RuntimeError(f"falharam {len(erros)} entidades: {erros}")
