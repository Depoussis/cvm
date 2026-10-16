# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze · BCB SGS
# MAGIC Descarrega as séries de `config/series/bcb_sgs.yaml` da API SGS, guarda cada resposta original no volume
# MAGIC `ops.raw` e acrescenta os registos (texto, sem conversões) a `bronze.bcb_sgs_valores`.
# MAGIC
# MAGIC - **incremental**: do watermark menos `revisao_dias` até hoje (sem watermark = backfill).
# MAGIC - **backfill**: de `inicio_backfill` até hoje. **reprocess**: `data_inicio`..`data_fim`.
# MAGIC - Uma resposta com o mesmo hash de outra já processada não volta a entrar na bronze (status `DUPLICATE`).

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
from src.ingestion.bcb_sgs.client import Serie, extrair

logging.basicConfig(level=logging.INFO)
FONTE = "bcb_sgs"
fonte = carregar_yaml("sources/bcb.yaml")
series = [Serie.de_config(s) for s in carregar_yaml("series/bcb_sgs.yaml")["series"]]
series = [s for s in series if p.escolhida(s.entidade)]
cliente = ClienteHttp(fonte["http"])
tabela = f"{p.catalogo}.bronze.bcb_sgs_valores"
hoje = date.today()

# COMMAND ----------

erros = {}
for serie in series:
    wm = control.ler_watermark(spark, p.catalogo, FONTE, serie.entidade)
    inicio, fim = janela.intervalo(p.run_mode, serie.inicio_backfill, serie.revisao_dias, hoje,
                                   date.fromisoformat(wm["watermark_value"]) if wm else None,
                                   p.data_inicio, p.data_fim)
    e = control.Execucao(p.catalogo, p.run_id, "bronze_bcb_sgs", FONTE, serie.entidade, "bronze", p.run_mode,
                         inicio.isoformat(), fim.isoformat(), {"codigo": serie.codigo})
    control.iniciar(spark, e)
    c = control.Contagens()
    try:
        ja_processados = writer.hashes_processados(spark, p.catalogo, FONTE, serie.entidade)
        linhas, registos_ficheiro = [], []
        for pg in extrair(cliente, fonte["bcb_sgs"]["url"], serie, inicio, fim, fonte["bcb_sgs"]["janela_max_anos"]):
            h = raw_store.sha256(pg.conteudo)
            caminho = raw_store.caminho_raw(p.catalogo, FONTE, serie.entidade, hoje, p.run_id,
                                            f"sgs_{serie.codigo}_{pg.inicio:%Y%m%d}_{pg.fim:%Y%m%d}.json")
            raw_store.gravar(caminho, pg.conteudo)
            origem = writer.Origem(FONTE, serie.entidade, pg.url, caminho, h, len(pg.conteudo), pg.inicio, pg.fim)
            c.read += len(pg.registos)
            periodo = f"{pg.inicio}/{pg.fim}"
            if h in ja_processados:
                c.unchanged += len(pg.registos)
                registos_ficheiro.append(writer.linha_registo(origem, p.run_id, "DUPLICATE",
                                                              "payload idêntico a um já processado", periodo))
                continue
            negocio = [{"serie_codigo": serie.codigo, "data": r["data"], "valor": r["valor"]} for r in pg.registos]
            linhas += writer.linhas_bronze(negocio, origem, p.run_id)
            registos_ficheiro.append(writer.linha_registo(
                origem, p.run_id, "PROCESSED", "sem valores na janela (404)" if pg.status == 404 else None, periodo))
        c.inserted = writer.append(spark, tabela, linhas)
        writer.registar_ficheiros(spark, p.catalogo, registos_ficheiro)
        control.concluir(spark, e, c)
        print(f"{serie.entidade}: {inicio}..{fim} lidos={c.read} bronze={c.inserted} duplicados={c.unchanged}")
    except Exception as ex:  # regista e continua com as outras séries; o notebook falha no fim
        control.falhar(spark, e, ex, c)
        erros[serie.entidade] = repr(ex)

if erros:
    raise RuntimeError(f"falharam {len(erros)} séries: {erros}")

# COMMAND ----------

display(spark.sql(f"""
  SELECT entity_name, execution_status, records_read, records_inserted, records_unchanged, watermark_start, watermark_end
  FROM {p.catalogo}.control.pipeline_execution WHERE pipeline_run_id = '{p.run_id}' AND layer = 'bronze'
  ORDER BY entity_name"""))
