# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze · B3 proventos e eventos societários
# MAGIC API pública "Empresas listadas" da B3 (`src/ingestion/b3/proventos.py`, `config/datasets/b3.yaml: proventos`):
# MAGIC 1. lista de empresas (paginada);
# MAGIC 2. para cada companhia com ações negociadas nos últimos `anos_atividade` anos: complemento (número de ações,
# MAGIC    desdobramentos/grupamentos/bonificações) e histórico completo de dividendos e JCP (paginado).
# MAGIC
# MAGIC Todas as respostas vão para um único ficheiro JSON Lines no volume `ops.raw` (original imutável). Um registo sem
# MAGIC as chaves esperadas (schema drift) faz a execução falhar. A bronze recebe uma cópia completa por execução;
# MAGIC a silver fica com a mais recente.

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
from collections import defaultdict
from datetime import date

from src.audit import control
from src.bronze import writer
from src.common import raw_store
from src.common.config import carregar_yaml
from src.common.http import ClienteHttp, ErroFonte
from src.ingestion.b3 import proventos as pv

logging.basicConfig(level=logging.INFO)
FONTE, ENTIDADE = "b3", "proventos"
cfg = carregar_yaml("datasets/b3.yaml")["proventos"]
cliente = ClienteHttp(carregar_yaml("sources/bcb.yaml")["http"]
                      | {"pausa_entre_pedidos_s": cfg["pausa_entre_pedidos_s"], "timeout_s": 60})
hoje = date.today()
k = p.catalogo
respostas: list[tuple[str, bytes]] = []


def pedir(url: str):
    r = cliente.get(url)
    respostas.append((url, r.conteudo))
    return json.loads(r.conteudo)

# COMMAND ----------

if p.escolhida(ENTIDADE):
    e = control.Execucao(k, p.run_id, "bronze_b3_proventos", FONTE, ENTIDADE, "bronze", p.run_mode)
    control.iniciar(spark, e)
    c = control.Contagens()
    try:
        # 1. empresas
        primeira = pedir(pv.url_empresas(1))
        empresas = list(primeira["results"])
        for pagina in range(2, pv.paginas(primeira) + 1):
            empresas += pedir(pv.url_empresas(pagina))["results"]
        drift = {x for emp in empresas for x in pv.chaves_em_falta(emp, pv.CHAVES_EMPRESA)}
        if drift:
            raise ValueError(f"lista de empresas sem as chaves {sorted(drift)} (schema drift)")

        # 2. emissores com ações negociadas recentemente (raiz de 4 letras do ticker)
        ativos = {r[0] for r in spark.sql(f"""
            SELECT DISTINCT substr(ticker, 1, 4) FROM {k}.gold.dim_ativo_b3
            WHERE classe_ativo = 'Ação' AND ultimo_pregao >= add_months(current_date(), -12 * {cfg['anos_atividade']})
        """).collect()}
        por_emissor = {}
        for emp in empresas:
            if emp["issuingCompany"] in ativos:
                por_emissor.setdefault(emp["issuingCompany"], emp)
        print(f"{len(empresas)} empresas na B3; {len(por_emissor)} com ações negociadas nos últimos "
              f"{cfg['anos_atividade']} anos (de {len(ativos)} raízes de ticker)")

        complementos, eventos, dinheiro, falhas = {}, [], [], {}
        for emissor in sorted(por_emissor):
            try:
                comp = pedir(pv.url_complemento(emissor))
                comp = comp[0] if isinstance(comp, list) and comp else comp
                if not comp:
                    falhas[emissor] = "complemento vazio"
                    continue
                if pv.chaves_em_falta(comp, pv.CHAVES_COMPLEMENTO):
                    raise ValueError(f"{emissor}: complemento sem {pv.chaves_em_falta(comp, pv.CHAVES_COMPLEMENTO)}")
                complementos[emissor] = (respostas[-1][0], comp)
                for ev in comp.get("stockDividends") or []:
                    eventos.append((respostas[-1][0], emissor, ev))
                nome = comp.get("tradingName") or por_emissor[emissor]["tradingName"]
                pagina, total = 1, 1
                while pagina <= total:
                    url = pv.url_dinheiro(nome.strip(), pagina)
                    d = pedir(url)
                    total = pv.paginas(d)
                    for x in d.get("results") or []:
                        if pv.chaves_em_falta(x, pv.CHAVES_DINHEIRO):
                            raise ValueError(f"{emissor}: provento sem {pv.chaves_em_falta(x, pv.CHAVES_DINHEIRO)}")
                        dinheiro.append((url, emissor, nome, x))
                    pagina += 1
            except ErroFonte as ex:
                falhas[emissor] = repr(ex)
        print(f"{len(complementos)} complementos, {len(eventos)} eventos em ações, {len(dinheiro)} proventos em "
              f"dinheiro, {len(respostas)} pedidos, {len(falhas)} falhas")

        # 3. original: todas as respostas num ficheiro JSON Lines
        conteudo = "\n".join(json.dumps({"url": u, "corpo": b.decode("utf-8", "replace")}, ensure_ascii=False)
                             for u, b in respostas).encode()
        caminho = raw_store.caminho_raw(k, FONTE, ENTIDADE, hoje, p.run_id, "respostas.jsonl")
        raw_store.gravar(caminho, conteudo)
        hash_ = raw_store.sha256(conteudo)
        origem = lambda url: writer.Origem(FONTE, ENTIDADE, url, caminho, hash_, len(conteudo), None, None)  # noqa: E731

        # 4. bronze
        grupos = defaultdict(list)
        for emp in empresas:
            grupos["empresas"].append(("lista", pv.registo("empresas", emp)))
        for emissor, (url, comp) in complementos.items():
            grupos["complemento"].append((url, pv.registo("complemento", comp, emissor=emissor)))
        for url, emissor, ev in eventos:
            grupos["eventos"].append((url, pv.registo("eventos", ev, emissor=emissor)))
        for url, emissor, nome, x in dinheiro:
            grupos["dinheiro"].append((url, pv.registo("dinheiro", x, emissor=emissor, nome_pregao_pedido=nome)))
        for tipo, linhas in grupos.items():
            tabela = f"{k}.bronze.{cfg['tabelas_bronze'][tipo]}"
            por_url = defaultdict(list)
            for url, r in linhas:
                por_url[url].append(r)
            bronze = [b for url, rs in por_url.items()
                      for b in writer.linhas_bronze(rs, origem(pv.url_empresas(1) if url == "lista" else url), p.run_id)]
            n = writer.append(spark, tabela, bronze)
            c.read += n
            c.inserted += n
            print(f"bronze.{cfg['tabelas_bronze'][tipo]}: {n} linhas")
        writer.registar_ficheiros(spark, k, [writer.linha_registo(
            origem(pv.BASE), p.run_id, "PROCESSED", f"{len(respostas)} respostas; falhas: {len(falhas)}", None)])
        e.parameters.update({"empresas": len(por_emissor), "pedidos": len(respostas), "falhas": falhas})
        # Falhas isoladas (ex.: empresa sem página) não param a carga; muitas indicam um problema na fonte.
        if len(falhas) > max(5, 0.05 * len(por_emissor)):
            raise RuntimeError(f"{len(falhas)} empresas falharam: {dict(list(falhas.items())[:10])}")
        control.concluir(spark, e, c)
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        raise
