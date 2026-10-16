# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze · CVM
# MAGIC 1. **Catálogo**: recursos dos pacotes CKAN usados (`bronze.cvm_catalogo_recursos`).
# MAGIC 2. **Ficheiros** de `config/datasets/cvm.yaml`: para cada URL, `HEAD` compara ETag/Last-Modified com a última
# MAGIC    versão registada; só descarrega o que mudou. O original (ZIP/CSV) vai para o volume `ops.raw`, os CSV são
# MAGIC    extraídos, a codificação é detetada e o cabeçalho é validado contra o contrato. Cabeçalho desconhecido →
# MAGIC    quarentena e falha. Conteúdo com o mesmo sha256 de uma versão já processada → `DUPLICATE`.
# MAGIC
# MAGIC Entidades (parâmetro `entidades`): `catalogo`, `fi_inf_diario`, `fi_registro`, `cia_aberta_cad`.

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

from src.audit import control
from src.bronze import csv_loader, writer
from src.common import raw_store
from src.common.config import carregar_yaml
from src.common.http import ClienteHttp
from src.ingestion.cvm import files as cvm

logging.basicConfig(level=logging.INFO)
FONTE = "cvm"
cfg = carregar_yaml("datasets/cvm.yaml")
cliente = ClienteHttp(carregar_yaml("sources/bcb.yaml")["http"] | {"pausa_entre_pedidos_s": 0.5, "timeout_s": 300})
hoje = date.today()
erros = {}

# COMMAND ----------

# MAGIC %md ## Catálogo CKAN

# COMMAND ----------

if p.escolhida("catalogo"):
    e = control.Execucao(p.catalogo, p.run_id, "bronze_cvm", FONTE, "catalogo", "bronze", p.run_mode)
    control.iniciar(spark, e)
    c = control.Contagens()
    try:
        linhas = []
        for pacote in cfg["ckan"]["pacotes"]:
            r = cliente.get(cfg["ckan"]["url_package_show"], params={"id": pacote})
            caminho = raw_store.caminho_raw(p.catalogo, FONTE, "catalogo", hoje, p.run_id, f"{pacote}.json")
            raw_store.gravar(caminho, r.conteudo)
            res = json.loads(r.conteudo)["result"]
            origem = writer.Origem(FONTE, "catalogo", r.url, caminho, raw_store.sha256(r.conteudo), len(r.conteudo), None, None)
            negocio = [{"pacote": res["name"], "titulo_pacote": res["title"], "pacote_modificado": res.get("metadata_modified"),
                        "recurso_id": x["id"], "nome": x.get("name"), "formato": x.get("format"), "url": x["url"],
                        "recurso_criado": x.get("created"), "recurso_modificado": x.get("last_modified")}
                       for x in res["resources"]]
            linhas += writer.linhas_bronze(negocio, origem, p.run_id)
        c.read = c.inserted = writer.append(spark, f"{p.catalogo}.bronze.cvm_catalogo_recursos", linhas)
        control.concluir(spark, e, c)
        print(f"catálogo: {c.inserted} recursos")
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        erros["catalogo"] = repr(ex)

# COMMAND ----------

# MAGIC %md ## Ficheiros

# COMMAND ----------

def alvos(nome: str, ds: dict) -> list[cvm.Alvo]:
    if ds["periodicidade"] == "mensal":
        ini = f"{p.data_inicio:%Y-%m}" if p.data_inicio else None
        fim = f"{p.data_fim:%Y-%m}" if p.data_fim else None
        return [cvm.Alvo(nome, cvm.url_mes(ds["url"], m), m) for m in cvm.meses_a_verificar(p.run_mode, ds, hoje, ini, fim)]
    return [cvm.Alvo(nome, ds["url"], None)]


def processar(alvo: cvm.Alvo, ds: dict, c: control.Contagens, ja: set[str], forcar: bool) -> str:
    """Devolve o estado: SEM_ALTERACAO, DUPLICATE ou PROCESSED."""
    h = cliente.head(alvo.url)
    if h.status == 404:
        return "NAO_PUBLICADO"
    if not forcar and not cvm.mudou(h.etag, h.last_modified, writer.ultimo_registo(spark, p.catalogo, alvo.url)):
        return "SEM_ALTERACAO"
    r = cliente.get(alvo.url)
    nome_remoto = alvo.url.rsplit("/", 1)[-1]
    caminho = raw_store.caminho_raw(p.catalogo, FONTE, alvo.dataset, hoje, p.run_id, nome_remoto)
    raw_store.gravar(caminho, r.conteudo)
    hash_ = raw_store.sha256(r.conteudo)
    origem = writer.Origem(FONTE, alvo.dataset, alvo.url, caminho, hash_, len(r.conteudo), None, None,
                           r.etag or h.etag, r.last_modified or h.last_modified)
    if hash_ in ja:
        writer.registar_ficheiros(spark, p.catalogo, [writer.linha_registo(
            origem, p.run_id, "DUPLICATE", "conteúdo idêntico a uma versão já processada", alvo.periodo)])
        return "DUPLICATE"

    # CSV dentro do ZIP (ou o próprio CSV); cada um é validado e carregado na sua tabela bronze
    pasta_extraidos = caminho.rsplit("/", 1)[0] + "/extraidos"
    for chave, f in ds["ficheiros"].items():
        if nome_remoto.endswith(".zip"):
            csvs = cvm.extrair_zip(r.conteudo, f["padrao_nome"])
        else:
            csvs = [(nome_remoto, r.conteudo)]
        if not csvs:
            raise ValueError(f"{alvo.url}: nenhum ficheiro '{f['padrao_nome']}' encontrado")
        tabela = f"{p.catalogo}.bronze.{f['tabela_bronze']}"
        cols_tabela = cvm.colunas_bronze(f["versoes"])
        csv_loader.garantir_tabela(spark, tabela, cols_tabela, f"CVM {alvo.dataset}/{chave}: como recebido (texto)",
                                   ["_reference_period"] if ds["periodicidade"] == "mensal" else [])
        for nome_csv, dados in csvs:
            codificacao = cvm.detectar_codificacao(dados)
            colunas = cvm.cabecalho(dados, codificacao, cfg["csv"]["separador"])
            versao = cvm.identificar_versao(colunas, f["versoes"])
            if versao is None:
                q = f"/Volumes/{p.catalogo}/ops/quarantine/{FONTE}/{alvo.dataset}/ingestion_date={hoje}/{p.run_id}"
                raw_store.gravar(f"{q}/{nome_csv}", dados)
                raw_store.gravar(f"{q}/{nome_csv}.motivo.json", json.dumps(
                    {"motivo": "cabeçalho fora do contrato", "colunas": colunas, "url": alvo.url}, ensure_ascii=False).encode())
                writer.registar_ficheiros(spark, p.catalogo, [writer.linha_registo(
                    origem, p.run_id, "QUARANTINED", f"{nome_csv}: cabeçalho desconhecido {colunas}", alvo.periodo)])
                raise ValueError(f"{nome_csv}: cabeçalho fora do contrato (schema drift): {colunas}")
            destino_csv = nome_remoto if not nome_remoto.endswith(".zip") else f"extraidos/{nome_csv}"
            caminho_csv = caminho if not nome_remoto.endswith(".zip") else f"{pasta_extraidos}/{nome_csv}"
            if nome_remoto.endswith(".zip"):
                raw_store.gravar(caminho_csv, dados)
            n = csv_loader.carregar_csv(spark, caminho_csv, tabela, colunas, codificacao, cfg["csv"]["separador"],
                                        versao, origem, alvo.periodo, p.run_id)
            c.read += n
            c.inserted += n
            print(f"  {destino_csv}: {n} linhas, {codificacao}, contrato {versao}")
    writer.registar_ficheiros(spark, p.catalogo, [writer.linha_registo(origem, p.run_id, "PROCESSED", None, alvo.periodo)])
    return "PROCESSED"


for nome, ds in cfg["datasets"].items():
    if not p.escolhida(nome):
        continue
    lista = alvos(nome, ds)
    e = control.Execucao(p.catalogo, p.run_id, "bronze_cvm", FONTE, nome, "bronze", p.run_mode,
                         lista[0].periodo if lista else None, lista[-1].periodo if lista else None,
                         {"ficheiros": len(lista)})
    control.iniciar(spark, e)
    c = control.Contagens()
    estados = {}
    try:
        ja = writer.hashes_processados(spark, p.catalogo, FONTE, nome)
        for alvo in lista:
            estado = processar(alvo, ds, c, ja, forcar=p.run_mode == "reprocess")
            estados[estado] = estados.get(estado, 0) + 1
            print(f"{nome} {alvo.periodo or ''}: {estado}")
        e.parameters["estados_ficheiros"] = estados  # contagens de linhas em `c`; estados por ficheiro aqui
        control.concluir(spark, e, c)  # o watermark (última data de competência) é confirmado pela silver
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        erros[nome] = repr(ex)

if erros:
    raise RuntimeError(f"falharam {len(erros)} entidades: {erros}")
