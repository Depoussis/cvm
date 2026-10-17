"""Compara a gold com fontes externas, linha a linha, e grava o relatório em docs/validacao/resultado.json.

Uso:  python scripts/validar_fontes.py --env dev [--so ptax ipca ...]

Cada verificação lê uma tabela da gold no SQL Warehouse, descarrega a mesma informação de outra fonte (independente
sempre que existe: IBGE, Copom, Yahoo Finance; senão o ficheiro original publicado de novo) e conta as linhas iguais,
as diferentes e as que só existem de um lado. Não altera nada na plataforma. Resultado explicado em
docs/validacao_dados.md.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import yaml

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from databricks.sdk import WorkspaceClient  # noqa: E402

from scripts.exportar_painel import consultar  # noqa: E402
from src.ingestion.b3 import cotahist  # noqa: E402
from src.common.config import carregar_ambiente, carregar_yaml  # noqa: E402

log = logging.getLogger("validar_fontes")
DESTINO = RAIZ / "docs" / "validacao" / "resultado.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141 Safari/537.36"}

# Papéis líquidos de cada classe (ações, FII, ETF) para a comparação com o Yahoo Finance.
PAPEIS = ["PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "ABEV3", "WEGE3", "B3SA3", "MGLU3", "RENT3", "SUZB3", "PETR3",
          "KNCR11", "HGLG11", "MXRF11", "XPML11", "BOVA11", "IVVB11", "SMAL11", "HASH11"]


def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers=UA, timeout=180, **kw)
    r.raise_for_status()
    return r


def _comparar(nosso: pd.DataFrame, fonte: pd.DataFrame, chave: list[str], colunas: dict[str, float],
              rotulos: dict[str, str] | None = None) -> dict:
    """Junta pelas chaves e compara cada coluna com a tolerância absoluta indicada ({coluna: tolerância})."""
    m = nosso.merge(fonte, on=chave, how="outer", suffixes=("_nosso", "_fonte"), indicator=True)
    ambos = m[m["_merge"] == "both"].copy()
    ok = pd.Series(True, index=ambos.index)
    difs = {}
    for c, tol in colunas.items():
        a, b = ambos[f"{c}_nosso"].astype(float), ambos[f"{c}_fonte"].astype(float)
        d = (a - b).abs()
        igual = (d <= tol + 1e-12) | (a.isna() & b.isna())
        ok &= igual
        difs[c] = {"max_dif": None if d.dropna().empty else float(d.max()), "tolerancia": tol,
                   "diferentes": int((~igual).sum())}
        ambos[f"{c}_dif"] = a - b
    ambos["_ok"] = ok
    cols = chave + [x for c in colunas for x in (f"{c}_nosso", f"{c}_fonte", f"{c}_dif")]
    so_nosso = m[m["_merge"] == "left_only"][chave]
    so_fonte = m[m["_merge"] == "right_only"][chave]

    def registos(df: pd.DataFrame) -> list[dict]:
        out = df.copy()
        for c in out.columns:
            if pd.api.types.is_datetime64_any_dtype(out[c]):
                out[c] = out[c].dt.strftime("%Y-%m-%d")
        return json.loads(out.to_json(orient="records", force_ascii=False, date_format="iso"))

    return {
        "comparados": int(len(ambos)), "iguais": int(ok.sum()), "diferentes": int((~ok).sum()),
        "so_nosso": int(len(so_nosso)), "so_fonte": int(len(so_fonte)), "colunas": difs,
        "rotulos": rotulos or {},
        "amostra": registos(ambos.sort_values(chave).tail(8)[cols]),
        "divergencias": registos(ambos[~ok].sort_values(chave).head(15)[cols]),
        "exemplos_so_nosso": registos(so_nosso.sort_values(chave).head(10)),
        "exemplos_so_fonte": registos(so_fonte.sort_values(chave).head(10)),
    }


# --------------------------------------------------------------------------------------------- verificações

def v_ptax(q, k) -> dict:
    sql = (f"SELECT simbolo, data_cotacao, cotacao_compra, cotacao_venda\n  FROM {k}.gold.fct_ptax_diario\n"
           " WHERE simbolo IN ('USD', 'EUR') AND data_cotacao >= DATE'2015-01-01'")
    nosso = q(sql)
    nosso["data_cotacao"] = pd.to_datetime(nosso["data_cotacao"])
    hoje = date.today()
    url = ("https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/CotacaoMoedaPeriodo(moeda=@moeda,"
           "dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)?@moeda='{m}'&@dataInicial='01-01-2015'"
           f"&@dataFinalCotacao='{hoje:%m-%d-%Y}'&$format=json&$filter=tipoBoletim%20eq%20'Fechamento'")
    linhas = []
    for m in ("USD", "EUR"):
        for v in _get(url.format(m=m)).json()["value"]:
            linhas.append({"simbolo": m, "data_cotacao": v["dataHoraCotacao"][:10],
                           "cotacao_compra": v["cotacaoCompra"], "cotacao_venda": v["cotacaoVenda"],
                           "hora": v["dataHoraCotacao"]})
    fonte = pd.DataFrame(linhas)
    fonte["data_cotacao"] = pd.to_datetime(fonte["data_cotacao"])
    # a PTAX publica por vezes dois boletins de fechamento no mesmo dia: vale o último (como na plataforma)
    fonte = fonte.sort_values("hora").drop_duplicates(["simbolo", "data_cotacao"], keep="last").drop(columns="hora")
    return {"titulo": "PTAX de fechamento (dólar e euro)", "tabela": f"{k}.gold.fct_ptax_diario", "sql": sql,
            "fonte": "Banco Central, API Olinda (boletim de fechamento)", "url": url.format(m="USD"),
            "independente": False, "chave": ["simbolo", "data_cotacao"],
            **_comparar(nosso, fonte, ["simbolo", "data_cotacao"], {"cotacao_compra": 1e-6, "cotacao_venda": 1e-6})}


def v_selic(q, k) -> dict:
    sql = (f"SELECT data_referencia AS data, valor AS meta_selic\n  FROM {k}.gold.fct_serie_valor\n"
           " WHERE serie_codigo = 432   -- meta Selic definida pelo Copom (% a.a.)")
    nosso = q(sql)
    nosso["data"] = pd.to_datetime(nosso["data"])
    url = "https://www.bcb.gov.br/api/servico/sitebcb/historicotaxasjuros"
    reunioes = _get(url).json()["conteudo"]
    linhas = []
    for r in reunioes:
        ini = pd.Timestamp(r["DataInicioVigencia"][:10])
        fim = pd.Timestamp(r["DataFimVigencia"][:10]) if r["DataFimVigencia"] else nosso["data"].max()
        for d in pd.date_range(ini, fim):
            linhas.append({"data": d, "meta_selic": r["MetaSelic"], "reuniao": r["NumeroReuniaoCopom"]})
    fonte = pd.DataFrame(linhas).sort_values("reuniao").drop_duplicates("data", keep="last").drop(columns="reuniao")
    fonte = fonte[(fonte["data"] >= nosso["data"].min()) & (fonte["data"] <= nosso["data"].max())]
    res = _comparar(nosso, fonte, ["data"], {"meta_selic": 1e-9})
    # desempate: o valor que a própria API SGS publica nesses dias (é a origem da série 432)
    datas = [d["data"] for d in res["divergencias"]] + [d["data"] for d in res["exemplos_so_nosso"]]
    sgs = []
    for d in datas:
        dd = date.fromisoformat(d)
        v = _get(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados?formato=json&dataInicial={dd:%d/%m/%Y}"
                 f"&dataFinal={dd:%d/%m/%Y}").json()
        sgs.append({"data": d, "dia_semana": ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"][dd.weekday()],
                    "sgs_api": float(v[0]["valor"]) if v else None,
                    "nosso": float(nosso.loc[nosso["data"] == pd.Timestamp(d), "meta_selic"].iloc[0])})
    res["desempate_sgs"] = sgs
    return {"titulo": "Meta Selic (série SGS 432) contra as decisões do Copom", "tabela": f"{k}.gold.fct_serie_valor",
            "sql": sql, "fonte": "Banco Central, histórico das reuniões do Copom (site do BCB)", "url": url,
            "independente": True, "chave": ["data"], **res}


def v_ipca(q, k) -> dict:
    sql = (f"SELECT data_referencia AS mes, valor AS ipca_mes\n  FROM {k}.gold.fct_serie_valor\n"
           " WHERE serie_codigo = 433   -- IPCA, variação mensal (%)")
    nosso = q(sql)
    nosso["mes"] = pd.to_datetime(nosso["mes"])
    url = "https://apisidra.ibge.gov.br/values/t/1737/n1/all/v/63/p/all"
    dados = _get(url).json()[1:]
    fonte = pd.DataFrame([{"mes": pd.Timestamp(int(d["D3C"][:4]), int(d["D3C"][4:]), 1), "ipca_mes": float(d["V"])}
                          for d in dados if d["V"] not in ("...", "-", "")])
    fonte = fonte[fonte["mes"] >= nosso["mes"].min()]
    return {"titulo": "IPCA mensal (série SGS 433) contra o IBGE", "tabela": f"{k}.gold.fct_serie_valor", "sql": sql,
            "fonte": "IBGE, SIDRA tabela 1737 (variação mensal do IPCA)", "url": url, "independente": True,
            "chave": ["mes"], **_comparar(nosso, fonte, ["mes"], {"ipca_mes": 1e-9})}


def _yahoo(simbolo: str, inicio: date) -> dict:
    p1 = int(datetime(inicio.year, inicio.month, inicio.day, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime.now(timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}?period1={p1}&period2={p2}&interval=1d"
           "&events=div%7Csplit")
    r = _get(url).json()["chart"]["result"][0]
    tz = timezone(timedelta(seconds=r["meta"]["gmtoffset"]))
    datas = [datetime.fromtimestamp(t, tz).date() for t in r.get("timestamp", [])]
    fechos = r["indicators"]["quote"][0]["close"]
    div = [{"data_ex": datetime.fromtimestamp(v["date"], tz).date(), "valor": v["amount"]}
           for v in r.get("events", {}).get("dividends", {}).values()]
    spl = [{"data_ex": pd.Timestamp(datetime.fromtimestamp(v["date"], tz).date()),
            "fator": v["denominator"] / v["numerator"]} for v in r.get("events", {}).get("splits", {}).values()]
    return {"url": url, "fechos": pd.DataFrame({"data": pd.to_datetime(datas), "fecho": fechos}).dropna(),
            "dividendos": pd.DataFrame(div, columns=["data_ex", "valor"]),
            "splits": pd.DataFrame(spl, columns=["data_ex", "fator"])}


_cache_yahoo: dict[str, dict] = {}


def _yahoo_cache(simbolo: str, inicio: date) -> dict:
    if simbolo not in _cache_yahoo:
        _cache_yahoo[simbolo] = _yahoo(simbolo, inicio)
    return _cache_yahoo[simbolo]


def _por_ticker(m: pd.DataFrame, ok: pd.Series) -> list[dict]:
    g = m.assign(ok=ok).groupby("ticker")["ok"].agg(["size", "sum"]).reset_index()
    return [{"ticker": r.ticker, "comparados": int(r.size), "iguais": int(r.sum)} for r in g.itertuples()]


def v_cotacoes(q, k) -> dict:
    """Fecho bruto do último ano ao cêntimo e retorno diário de todo o histórico."""
    lista = ", ".join(f"'{p}'" for p in PAPEIS)
    sql = (f"SELECT ticker, data_pregao AS data, preco_fechamento, retorno_dia\n  FROM {k}.gold.fct_cotacao_diaria\n"
           f" WHERE ticker IN ({lista})")
    nosso = q(sql)
    nosso["data"] = pd.to_datetime(nosso["data"])
    inicio = nosso["data"].min().date()
    partes = []
    for p in PAPEIS:
        y = _yahoo_cache(f"{p}.SA", inicio)
        f = y["fechos"].sort_values("data").copy()
        # o fecho do Yahoo vem ajustado aos desdobramentos/bonificações posteriores: desfazer para ter o fecho bruto
        f["fator_depois"] = [y["splits"].loc[y["splits"]["data_ex"] > d, "fator"].prod() for d in f["data"]]
        f["preco_fechamento"] = f["fecho"] / f["fator_depois"]
        f["retorno_dia"] = f["fecho"].pct_change()
        partes.append(f.assign(ticker=p))
    fonte = pd.concat(partes)
    fonte = fonte[(fonte["data"] >= nosso["data"].min()) & (fonte["data"] <= nosso["data"].max())]
    um_ano = nosso["data"].max() - pd.DateOffset(years=1)
    # (1) fecho do dia, último ano, ao cêntimo
    a, b = nosso[nosso["data"] > um_ano], fonte[fonte["data"] > um_ano]
    res = _comparar(a[["ticker", "data", "preco_fechamento"]], b[["ticker", "data", "preco_fechamento"]],
                    ["ticker", "data"], {"preco_fechamento": 0.0051})
    m = a.merge(b, on=["ticker", "data"], suffixes=("_nosso", "_fonte"))
    res["por_ticker"] = _por_ticker(m, (m["preco_fechamento_nosso"] - m["preco_fechamento_fonte"]).abs() <= 0.0051)
    res["periodo"] = f"{(um_ano + pd.Timedelta(days=1)):%d/%m/%Y} a {nosso['data'].max():%d/%m/%Y}"
    # desempate dos dias diferentes: o ficheiro diário oficial da B3 (COTAHIST_D), descarregado de novo
    dif = m[(m["preco_fechamento_nosso"] - m["preco_fechamento_fonte"]).abs() > 0.0051]
    modelo = carregar_yaml("datasets/b3.yaml")["cotahist"]["url_diario"]
    arquivo = {}
    for d in sorted(dif["data"].dt.date.unique()):
        try:
            z = zipfile.ZipFile(io.BytesIO(_get(cotahist.url_dia(modelo, d)).content))
        except (requests.HTTPError, zipfile.BadZipFile):
            continue
        for linha in z.open(z.namelist()[0]).read().decode("latin-1").splitlines():
            if linha[:2] == "01" and linha[24:27] == "010":
                r = cotahist.parse_linha(linha)
                arquivo[(r["codneg"], pd.Timestamp(d))] = cotahist.valor("preult", r["preult"])
    dif = dif.assign(b3_arquivo=[arquivo.get((t, d)) for t, d in zip(dif["ticker"], dif["data"])]).dropna(
        subset=["b3_arquivo"])
    res["desempate_cotahist"] = {
        "dias": int(len(dif)),
        "nosso_igual_ficheiro": int(((dif["preco_fechamento_nosso"] - dif["b3_arquivo"]).abs() < 0.005).sum()),
        "yahoo_igual_ficheiro": int(((dif["preco_fechamento_fonte"] - dif["b3_arquivo"]).abs() < 0.005).sum()),
        "exemplos": json.loads(dif.head(12).assign(data=dif["data"].dt.strftime("%Y-%m-%d"))[
            ["ticker", "data", "preco_fechamento_nosso", "preco_fechamento_fonte", "b3_arquivo"]].to_json(
            orient="records"))}
    # (2) retorno do dia em todo o histórico (já com eventos): 0,11 pp cobre o arredondamento ao cêntimo
    ret = _comparar(nosso[["ticker", "data", "retorno_dia"]].dropna(), fonte[["ticker", "data", "retorno_dia"]].dropna(),
                    ["ticker", "data"], {"retorno_dia": 0.0011})
    m = nosso.merge(fonte, on=["ticker", "data"], suffixes=("_nosso", "_fonte")).dropna(
        subset=["retorno_dia_nosso", "retorno_dia_fonte"])
    ret["por_ticker"] = _por_ticker(m, (m["retorno_dia_nosso"] - m["retorno_dia_fonte"]).abs() <= 0.0011)
    ret["periodo"] = f"{nosso['data'].min():%d/%m/%Y} a {nosso['data'].max():%d/%m/%Y}"
    res["retorno"] = ret
    return {"titulo": f"Cotações de {len(PAPEIS)} papéis (ações, FII e ETF)",
            "tabela": f"{k}.gold.fct_cotacao_diaria", "sql": sql,
            "fonte": "Yahoo Finance (fecho diário; desdobramentos desfeitos para o fecho bruto)",
            "url": _cache_yahoo["PETR4.SA"]["url"], "independente": True, "chave": ["ticker", "data"], **res}


def v_proventos(q, k) -> dict:
    """Ações e ETF por data ex; FII por mês (a plataforma estima o rendimento do FII pelo informe mensal da CVM)."""
    lista = ", ".join(f"'{p}'" for p in PAPEIS)
    sql = (f"SELECT ticker, classe_ativo,\n"
           f"       CASE WHEN classe_ativo = 'FII' THEN trunc(data_com, 'MM') ELSE data_ex END AS data_ex,\n"
           f"       round(sum(valor_ajustado), 6) AS valor\n"
           f"  FROM {k}.gold.fct_provento JOIN {k}.gold.dim_ativo_b3 USING (ticker)\n"
           f" WHERE ticker IN ({lista}) AND data_ex >= DATE'2021-01-05'\n GROUP BY ALL")
    nosso = q(sql)
    nosso["data_ex"] = pd.to_datetime(nosso["data_ex"])
    fii = set(nosso.loc[nosso["classe_ativo"] == "FII", "ticker"])
    nosso = nosso.drop(columns="classe_ativo")
    partes = []
    for p in PAPEIS:
        d = _yahoo_cache(f"{p}.SA", date(2021, 1, 4))["dividendos"].assign(ticker=p)
        d["data_ex"] = pd.to_datetime(d["data_ex"])
        if p in fii:   # o rendimento do mês M fica ex no mês M+1: comparar com o mês de referência M
            d["data_ex"] = (d["data_ex"].dt.to_period("M") - 1).dt.to_timestamp()
        partes.append(d)
    fonte = pd.concat(partes)
    fonte = fonte[(fonte["data_ex"] >= pd.Timestamp("2021-01-05")) & (fonte["data_ex"] <= nosso["data_ex"].max())]
    fonte = fonte.groupby(["ticker", "data_ex"], as_index=False)["valor"].sum()
    res = _comparar(nosso, fonte, ["ticker", "data_ex"], {"valor": 0.0005})
    m = nosso.merge(fonte, on=["ticker", "data_ex"], suffixes=("_nosso", "_fonte"))
    rel = (m["valor_nosso"] / m["valor_fonte"] - 1).abs()
    res["relativo"] = {"ate_1pct": int((rel <= 0.01).sum()), "ate_5pct": int((rel <= 0.05).sum()),
                       "acima_5pct": int((rel > 0.05).sum()), "total": int(len(rel))}
    res["por_ticker"] = _por_ticker(m, (m["valor_nosso"] - m["valor_fonte"]).abs() <= 0.0005)
    m["razao"] = m["valor_nosso"] / m["valor_fonte"]
    for linha in res["por_ticker"]:
        g = m[m["ticker"] == linha["ticker"]]
        linha["ate_1pct"] = int(((g["razao"] - 1).abs() <= 0.01).sum())
        linha["razao_mediana"] = round(float(g["razao"].median()), 4)
        linha["classe"] = "FII" if linha["ticker"] in fii else "Ação/ETF"
    return {"titulo": "Proventos (dividendos, JCP e rendimentos de FII)", "tabela": f"{k}.gold.fct_provento",
            "sql": sql, "fonte": "Yahoo Finance (eventos de dividendos)", "url": _cache_yahoo["PETR4.SA"]["url"],
            "independente": True, "chave": ["ticker", "data_ex"], **res}


def v_eventos(q, k) -> dict:
    """Desdobramentos, grupamentos e bonificações das 100 ações mais negociadas contra os 'splits' do Yahoo."""
    sql = (f"WITH top AS (\n  SELECT ticker FROM {k}.gold.fct_cotacao_diaria\n"
           "   WHERE classe_ativo = 'Ação' AND data_pregao >= add_months(current_date(), -12)\n"
           "   GROUP BY ticker ORDER BY sum(volume) DESC LIMIT 100)\n"
           "SELECT c.ticker, c.data_pregao AS data_ex, c.fator_evento, c.retorno_dia, c.preco_fechamento,\n"
           "       lag(c.preco_fechamento) OVER (PARTITION BY c.ticker ORDER BY c.data_pregao) AS fecho_anterior\n"
           f"  FROM {k}.gold.fct_cotacao_diaria c JOIN top USING (ticker)")
    todos = q(sql)
    todos["data_ex"] = pd.to_datetime(todos["data_ex"])
    nosso = todos[(todos["fator_evento"] - 1).abs() > 1e-9][["ticker", "data_ex", "fator_evento"]]
    linhas, url = [], None
    for t in sorted(todos["ticker"].unique()):
        p1 = int(datetime(2021, 1, 5, tzinfo=timezone.utc).timestamp())
        u = (f"https://query1.finance.yahoo.com/v8/finance/chart/{t}.SA?period1={p1}"
             f"&period2={int(datetime.now(timezone.utc).timestamp())}&interval=1d&events=split")
        url = url or u
        try:
            r = _get(u).json()["chart"]["result"][0]
        except (requests.HTTPError, KeyError, TypeError, IndexError):
            continue
        tz = timezone(timedelta(seconds=r["meta"]["gmtoffset"]))
        for v in r.get("events", {}).get("splits", {}).values():
            linhas.append({"ticker": t, "data_ex": pd.Timestamp(datetime.fromtimestamp(v["date"], tz).date()),
                           "fator_evento": v["denominator"] / v["numerator"]})
    fonte = pd.DataFrame(linhas, columns=["ticker", "data_ex", "fator_evento"])
    fonte = fonte[fonte["data_ex"] <= todos["data_ex"].max()]
    res = _comparar(nosso, fonte, ["ticker", "data_ex"], {"fator_evento": 0.002})
    # no dia de um evento que só o Yahoo tem, o fecho da B3 mostra se o evento aconteceu: a razão do fecho
    # fica perto do fator (sem evento, ficaria perto de 1)
    so_y = fonte.merge(nosso, on=["ticker", "data_ex"], how="left", indicator=True)
    so_y = so_y[so_y["_merge"] == "left_only"].drop(columns=["_merge", "fator_evento_y"]).rename(
        columns={"fator_evento_x": "fator_yahoo"})
    so_y = so_y.merge(todos[["ticker", "data_ex", "preco_fechamento", "fecho_anterior"]], on=["ticker", "data_ex"])
    so_y["razao_fecho_b3"] = so_y["preco_fechamento"] / so_y["fecho_anterior"]
    # suspeita de bonificação em falta: o fecho da B3 está mais perto do fator do Yahoo do que de "sem evento"
    so_y["suspeita"] = (so_y["razao_fecho_b3"] / so_y["fator_yahoo"] - 1).abs() < (so_y["razao_fecho_b3"] - 1).abs()
    res["so_yahoo_detalhe"] = json.loads(so_y.assign(data_ex=so_y["data_ex"].dt.strftime("%Y-%m-%d"))
                                         .to_json(orient="records", force_ascii=False))
    res["bonificacoes_suspeitas"] = int(so_y["suspeita"].sum())
    res["tickers"] = int(todos["ticker"].nunique())
    return {"titulo": "Desdobramentos, grupamentos e bonificações (100 ações mais negociadas)",
            "tabela": f"{k}.gold.fct_cotacao_diaria", "sql": sql, "fonte": "Yahoo Finance (eventos 'split')",
            "url": url, "independente": True, "chave": ["ticker", "data_ex"], **res}


def v_indices(q, k) -> dict:
    # o Yahoo não tem o histórico do IFIX (IFIX.SA devolve um só ponto): só o Ibovespa tem fonte externa
    sql = (f"SELECT indice, data_pregao AS data, fechamento\n  FROM {k}.gold.fct_indice_diario\n"
           " WHERE indice = 'IBOV'")
    nosso = q(sql)
    nosso["data"] = pd.to_datetime(nosso["data"])
    y = _yahoo("%5EBVSP", nosso["data"].min().date())
    fonte = y["fechos"].assign(indice="IBOV").rename(columns={"fecho": "fechamento"})
    fonte = fonte[(fonte["data"] >= nosso["data"].min()) & (fonte["data"] <= nosso["data"].max())]
    fonte["fechamento"] = fonte["fechamento"].round(2)
    res = _comparar(nosso, fonte, ["indice", "data"], {"fechamento": 1.0})
    m = nosso.merge(fonte, on=["indice", "data"], suffixes=("_nosso", "_fonte")).sort_values("data")
    rel = (m["fechamento_nosso"] / m["fechamento_fonte"] - 1).abs()
    res["relativo"] = {"ate_0_1pct": int((rel <= 0.001).sum()), "ate_1pct": int((rel <= 0.01).sum()),
                       "acima_1pct": int((rel > 0.01).sum()), "total": int(len(rel))}
    # desempate nos dias diferentes: o ETF BOVA11 replica o Ibovespa, por isso a variação do dia do índice certo
    # tem de ficar perto da variação do BOVA11 (fecho do Yahoo, fonte independente da nossa).
    bova = _yahoo("BOVA11.SA", nosso["data"].min().date())["fechos"].set_index("data")["fecho"]
    m["ret_nosso"] = m["fechamento_nosso"].pct_change()
    m["ret_yahoo"] = m["fechamento_fonte"].pct_change()
    m["ret_bova11"] = m["data"].map(bova.pct_change())
    dif = m[(m["fechamento_nosso"] - m["fechamento_fonte"]).abs() > 1.0].dropna(subset=["ret_bova11"])
    err_nosso = (dif["ret_nosso"] - dif["ret_bova11"]).abs()
    err_yahoo = (dif["ret_yahoo"] - dif["ret_bova11"]).abs()
    res["desempate_bova11"] = {
        "dias": int(len(dif)), "nosso_mais_perto": int((err_nosso < err_yahoo).sum()),
        "yahoo_mais_perto": int((err_yahoo < err_nosso).sum()),
        "erro_medio_nosso_pp": float(err_nosso.mean() * 100), "erro_medio_yahoo_pp": float(err_yahoo.mean() * 100),
        "erro_medio_todos_os_dias_pp": float((m["ret_nosso"] - m["ret_bova11"]).abs().mean() * 100)}
    return {"titulo": "Ibovespa (fecho diário)", "tabela": f"{k}.gold.fct_indice_diario", "sql": sql,
            "fonte": "Yahoo Finance (^BVSP); desempate com o ETF BOVA11", "url": y["url"], "independente": True,
            "chave": ["indice", "data"], **res}


def v_fundos(q, k) -> dict:
    mes = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)   # último mês fechado
    fim = (mes + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    sql = (f"SELECT cnpj_classe, id_subclasse, dt_comptc, vl_quota, vl_patrim_liq, nr_cotst\n"
           f"  FROM {k}.gold.fct_fundo_diario\n WHERE dt_comptc BETWEEN DATE'{mes}' AND DATE'{fim}'")
    nosso = q(sql)
    nosso["dt_comptc"] = pd.to_datetime(nosso["dt_comptc"])
    url = f"https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_{mes:%Y%m}.zip"
    resposta = _get(url)
    z = zipfile.ZipFile(io.BytesIO(resposta.content))
    nome = next(n for n in z.namelist() if n.endswith(".csv"))
    f = pd.read_csv(z.open(nome), sep=";", encoding="latin-1", dtype=str)
    cnpj = f.get("CNPJ_FUNDO_CLASSE", f.get("CNPJ_FUNDO")).str.replace(r"\D", "", regex=True)
    fonte = pd.DataFrame({"cnpj_classe": cnpj, "id_subclasse": f.get("ID_SUBCLASSE", "").fillna("").str.strip(),
                          "dt_comptc": pd.to_datetime(f["DT_COMPTC"]),
                          "vl_quota": pd.to_numeric(f["VL_QUOTA"]), "vl_patrim_liq": pd.to_numeric(f["VL_PATRIM_LIQ"]),
                          "nr_cotst": pd.to_numeric(f["NR_COTST"])})
    linhas_ficheiro = len(fonte)
    fonte = fonte.drop_duplicates(["cnpj_classe", "id_subclasse", "dt_comptc"], keep="last")
    # cota com 1e-6: cotas de dezenas de milhões só cabem com ~8 decimais num float64
    res = _comparar(nosso, fonte, ["cnpj_classe", "id_subclasse", "dt_comptc"],
                    {"vl_quota": 1e-6, "vl_patrim_liq": 0.005, "nr_cotst": 0})
    res["linhas_ficheiro"] = linhas_ficheiro
    res["duplicadas_ficheiro"] = linhas_ficheiro - len(fonte)
    # a CVM reescreve o ficheiro do mês quando um administrador corrige um informe: comparar as datas
    carga = q(f"SELECT max(_ingestion_timestamp) AS t FROM {k}.bronze.cvm_fi_inf_diario "
              f"WHERE _source_url LIKE '%inf_diario_fi_{mes:%Y%m}%'")["t"].iloc[0]
    res["ficheiro_cvm_modificado"] = resposta.headers.get("Last-Modified")
    res["ultima_carga_plataforma"] = str(carga)
    return {"titulo": f"Informe diário de fundos, {mes:%m/%Y} (todas as linhas)", "tabela": f"{k}.gold.fct_fundo_diario",
            "sql": sql, "fonte": "CVM, ficheiro original do portal de dados abertos (descarregado de novo)", "url": url,
            "independente": False, "chave": ["cnpj_classe", "id_subclasse", "dt_comptc"], **res}


def v_tesouro(q, k) -> dict:
    sql = (f"SELECT tipo_titulo, data_vencimento, data_base, taxa_compra, taxa_venda, pu_compra, pu_venda\n"
           f"  FROM {k}.gold.fct_tesouro_diario")
    nosso = q(sql)
    for c in ("data_vencimento", "data_base"):
        nosso[c] = pd.to_datetime(nosso[c])
    url = yaml.safe_load((RAIZ / "config" / "datasets" / "mercado.yaml").read_text(encoding="utf-8"))[
        "tesouro_direto"]["url"]
    leitor = csv.DictReader(io.StringIO(_get(url).content.decode("latin-1")), delimiter=";")
    linhas = []
    for r in leitor:
        def n(c: str) -> float | None:
            v = (r.get(c) or "").strip().replace(".", "").replace(",", ".")
            return float(v) if v else None
        linhas.append({"tipo_titulo": r["Tipo Titulo"].strip(),
                       "data_vencimento": pd.to_datetime(r["Data Vencimento"], dayfirst=True),
                       "data_base": pd.to_datetime(r["Data Base"], dayfirst=True),
                       "taxa_compra": n("Taxa Compra Manha"), "taxa_venda": n("Taxa Venda Manha"),
                       "pu_compra": n("PU Compra Manha"), "pu_venda": n("PU Venda Manha")})
    fonte = pd.DataFrame(linhas)
    fonte = fonte[fonte["data_base"] <= nosso["data_base"].max()]
    # a plataforma grava PU 0 como sem preço (NULL): a fonte é lida da mesma maneira para comparar
    for c in ("pu_compra", "pu_venda"):
        fonte.loc[fonte[c] == 0, c] = None
    chave = ["tipo_titulo", "data_vencimento", "data_base"]
    return {"titulo": "Tesouro Direto: preços e taxas (todas as linhas)", "tabela": f"{k}.gold.fct_tesouro_diario",
            "sql": sql, "fonte": "Tesouro Transparente, CSV original (descarregado de novo)", "url": url,
            "independente": False, "chave": chave,
            **_comparar(nosso, fonte, chave, {"taxa_compra": 1e-6, "taxa_venda": 1e-6, "pu_compra": 0.005,
                                              "pu_venda": 0.005})}


VERIFICACOES = {"ptax": v_ptax, "selic": v_selic, "ipca": v_ipca, "cotacoes": v_cotacoes, "proventos": v_proventos,
                "eventos": v_eventos, "indices": v_indices, "fundos": v_fundos, "tesouro": v_tesouro}


def _pct(a: float, b: float) -> float:
    return 100.0 if not b else 100.0 * a / b


# medidas de um resultado usadas pelos limites de config/validacao.yaml, além de iguais/comparados
METRICAS = {
    "plataforma_igual_b3_pct": lambda r: _pct(r["desempate_cotahist"]["nosso_igual_ficheiro"],
                                              r["desempate_cotahist"]["dias"]),
    "bonificacoes_suspeitas": lambda r: r.get("bonificacoes_suspeitas", 0),
    "acoes_ate_1pct_pct": lambda r: _pct(sum(t["ate_1pct"] for t in r["por_ticker"] if t["classe"] != "FII"),
                                         sum(t["comparados"] for t in r["por_ticker"] if t["classe"] != "FII")),
}


def avaliar_limites(verificacoes: dict, limites: dict) -> list[str]:
    """Alertas: verificações abaixo dos limites, com erro ou em falta."""
    alertas = []
    for nome, lim in limites.items():
        r = verificacoes.get(nome)
        if r is None or "erro" in r:
            alertas.append(f"{nome}: não correu ({(r or {}).get('erro', 'sem resultado')})")
            continue
        iguais = _pct(r["iguais"], r["comparados"])
        if "min_iguais_pct" in lim and iguais < lim["min_iguais_pct"]:
            alertas.append(f"{nome}: {iguais:.2f} % iguais, mínimo {lim['min_iguais_pct']} %")
        if "metrica" in lim:
            valor = METRICAS[lim["metrica"]](r)
            r.setdefault("metricas", {})[lim["metrica"]] = valor
            if "min_metrica" in lim and valor < lim["min_metrica"]:
                alertas.append(f"{nome}: {lim['metrica']} = {valor:.2f}, mínimo {lim['min_metrica']}")
            if "max_metrica" in lim and valor > lim["max_metrica"]:
                alertas.append(f"{nome}: {lim['metrica']} = {valor:.2f}, máximo {lim['max_metrica']}")
    return alertas


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--env", default="dev")
    ap.add_argument("--so", nargs="*", help="só estas verificações")
    ap.add_argument("--limites", action="store_true",
                    help="avalia config/validacao.yaml e sai com código 1 se houver alertas")
    args = ap.parse_args()
    cfg = carregar_ambiente(args.env)
    k = cfg["unity_catalog"]["catalog"]
    w = WorkspaceClient(host=cfg["databricks"]["host"], auth_type="azure-cli")
    wh = next(x for x in w.warehouses.list() if x.name == cfg["databricks"]["sql_warehouse_name"]).id

    def q(sql: str) -> pd.DataFrame:
        return consultar(w, wh, sql).to_pandas()

    relatorio = json.loads(DESTINO.read_text(encoding="utf-8")) if DESTINO.exists() else {"verificacoes": {}}
    for nome, f in VERIFICACOES.items():
        if args.so and nome not in args.so:
            continue
        log.info("a verificar %s", nome)
        agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            r = f(q, k)
        except Exception as ex:  # uma fonte em baixo não impede as outras verificações
            log.exception("%s falhou", nome)
            anterior = relatorio["verificacoes"].get(nome, {})
            relatorio["verificacoes"][nome] = {**anterior, "erro": repr(ex)[:500], "erro_em": agora}
            continue
        r["verificado_em"] = agora
        relatorio["verificacoes"][nome] = r
        log.info("%s: %s comparados, %s iguais, %s diferentes, só nosso %s, só fonte %s", nome, r["comparados"],
                 r["iguais"], r["diferentes"], r["so_nosso"], r["so_fonte"])
    alertas = []
    if args.limites:
        alertas = avaliar_limites(relatorio["verificacoes"], carregar_yaml("validacao.yaml")["limites"])
        relatorio["alertas"] = alertas
        relatorio["avaliado_em"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for a in alertas:
            log.error("ALERTA %s", a)
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(json.dumps(relatorio, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    log.info("relatório em %s; %d alertas", DESTINO.relative_to(RAIZ), len(alertas))
    return 1 if alertas else 0


if __name__ == "__main__":
    sys.exit(main())
