"""Bolsa (B3): ações, FII e ETF do mercado à vista, a partir das séries históricas COTAHIST."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from painel import dados, formato, graficos, ui

d = dados.tabela("b3_desempenho")
cot = dados.tabela("b3_cotacoes")
pregao = pd.Timestamp(d["data_referencia"].max())
ui.cabecalho("Bolsa", "Ações, fundos imobiliários e ETF do mercado à vista da B3 (séries históricas COTAHIST). "
             "Retornos de <b>preço</b>, ajustados a desdobramentos e grupamentos; não incluem dividendos.",
             selo=f"Pregão: {formato.data(pregao)}")

acoes = d[d["classe_ativo"] == "Ação"]
bova = d[d["ticker"] == "BOVA11"].squeeze() if (d["ticker"] == "BOVA11").any() else pd.Series(dtype=object)
dia = acoes["retorno_dia"].dropna()


def pct100(v, casas: int = 2, sinal: bool = True) -> str:
    return formato.pct(None if pd.isna(v) else v * 100, casas, sinal)


ui.kpis([
    {"rotulo": "Ibovespa (via BOVA11)", "valor": formato.brl(bova.get("fechamento")), "icone": "bolsa",
     "nota": f"{pct100(bova.get('retorno_dia'))} no dia" if len(bova) else None,
     "tom": "pos" if bova.get("retorno_dia", 0) >= 0 else "neg"},
    {"rotulo": "Ibovespa no ano", "valor": pct100(bova.get("retorno_ano"), 1), "icone": "subida",
     "nota": f"12 meses: {pct100(bova.get('retorno_12m'), 1)}",
     "tom": "pos" if bova.get("retorno_ano", 0) >= 0 else "neg"},
    {"rotulo": "Ações com negócios", "valor": formato.numero(len(acoes)), "icone": "camadas",
     "nota": f"{int((dia > 0).sum())} altas · {int((dia < 0).sum())} baixas no dia"},
    {"rotulo": "Volume médio diário em ações", "valor": formato.compacto(acoes["volume_medio_diario"].sum()),
     "icone": "fluxo", "nota": "últimos 30 dias, lote padrão"},
])

# ---------------------------------------------------------------- filtros dos rankings
CLASSES = {"Ações": "Ação", "FII": "FII", "ETF": "ETF e fundos"}
LIQUIDEZ = {"R$ 1 mi": 1e6, "R$ 10 mi": 1e7, "R$ 50 mi": 5e7, "Todos": 0}
f1, f2, f3, f4 = st.columns([1.4, 2.1, 1.1, 1.4])
classe = CLASSES[f1.segmented_control("Classe", list(CLASSES), default="Ações", key="b3_classe") or "Ações"]
base = d[d["classe_ativo"] == classe]
setores = sorted(base["setor"].dropna().unique())
escolha = f2.multiselect("Setor" if classe == "Ação" else "Segmento", setores, placeholder="Todos",
                         key=f"b3_setor_{classe}")
liq = LIQUIDEZ[f3.selectbox("Volume médio mínimo", list(LIQUIDEZ), key="b3_liq",
                            help="Volume financeiro médio por pregão nos últimos 30 dias")]
n = f4.segmented_control("Mostrar", [5, 10, 15], default=10, format_func=lambda x: f"Top {x}", key="b3_top") or 10
base = base[base["volume_medio_diario"] >= liq]
if escolha:
    base = base[base["setor"].isin(escolha)]
base = base.assign(fundo=base["nome_emissor"].fillna(base["nome_pregao"]))


def topo(col: str, menores: bool = False, filtro=None) -> pd.DataFrame:
    x = base if filtro is None else base[filtro]
    x = x.dropna(subset=[col])
    x = x.nsmallest(n, col) if menores else x.nlargest(n, col)
    return x.assign(valor=x[col] * 100)


sinal = lambda v: formato.pct(v, 2, sinal=True)  # noqa: E731
rankings = [
    ("Maiores altas do dia", topo("retorno_dia"), sinal, f"Variação no pregão de {formato.data(pregao)}"),
    ("Maiores baixas do dia", topo("retorno_dia", menores=True), sinal, "Variação no pregão"),
    ("Mais negociados", base.nlargest(n, "volume_medio_diario").assign(valor=lambda x: x["volume_medio_diario"]),
     formato.compacto, "Volume financeiro médio por pregão, 30 dias"),
    ("Maiores altas em 12 meses", topo("retorno_12m"), lambda v: formato.pct(v, 1, sinal=True), "Retorno de preço"),
    ("Maiores quedas em 12 meses", topo("retorno_12m", menores=True), lambda v: formato.pct(v, 1, sinal=True),
     "Retorno de preço"),
]
if classe == "FII":
    pvp = base[base["p_vp"].between(0.2, 3)]
    rankings.append(("Menor P/VP", pvp.nsmallest(n, "p_vp").assign(valor=lambda x: x["p_vp"]),
                     lambda v: formato.numero(v, 2), "Cotação / valor patrimonial da cota (último informe CVM)"))
else:
    rankings.append(("Maiores altas no ano", topo("retorno_ano"), lambda v: formato.pct(v, 1, sinal=True),
                     f"Desde o último pregão de {pregao.year - 1}"))
for inicio in (0, 3):
    for i, col in enumerate(st.columns(3, gap="medium"), start=inicio):
        titulo, df, fmt, sub = rankings[i]
        with col:
            ui.ranking(df, "valor", fmt, titulo, sub, chave=f"b3_rk_{i}")

# ---------------------------------------------------------------- evolução e setores
liquidos = d[d["ticker"].isin(cot["ticker"].unique())].sort_values("volume_medio_diario", ascending=False)
rotulos = {r.ticker: f"{r.ticker} · {(r.nome_emissor if pd.notna(r.nome_emissor) else r.nome_pregao)[:22]}"
           for r in liquidos.itertuples()}
PERIODOS = {"1M": 1, "6M": 6, "1A": 12, "3A": 36, "Tudo": None}

c1, c2 = st.columns([3, 2], gap="medium")
with c1, ui.card("b3_evolucao"):
    ui.titulo_card("Evolução do preço", "Base 100 no início do período · ajustado a desdobramentos, sem dividendos")
    a, b = st.columns([1, 1])
    padrao = [t for t in ("BOVA11", "PETR4", "VALE3", "ITUB4") if t in rotulos]
    tickers = a.multiselect("Papéis", list(rotulos), default=padrao, max_selections=6, format_func=rotulos.get,
                            placeholder="Escolha até 6 papéis", label_visibility="collapsed")
    p = b.segmented_control("Período", list(PERIODOS), default="1A", key="b3_periodo", label_visibility="collapsed")
    serie = cot[cot["ticker"].isin(tickers or padrao[:1])].sort_values("data")
    meses = PERIODOS[p or "1A"]
    if meses:
        serie = serie[serie["data"] >= serie["data"].max() - pd.DateOffset(months=meses)]
    serie = serie.assign(base100=serie.groupby("ticker")["preco_ajustado"].transform(lambda s: s / s.iloc[0] * 100))
    graficos.mostrar(graficos.linhas(serie, "data", "base100", "ticker", "", 1, altura=330))
with c2, ui.card("b3_setores"):
    ui.titulo_card("Setores em 12 meses", "Retorno mediano das ações com volume ≥ R$ 1 mi/dia (%)")
    s = (acoes[acoes["volume_medio_diario"] >= 1e6].dropna(subset=["retorno_12m"])
         .groupby("setor").agg(mediana=("retorno_12m", "median"), papeis=("ticker", "count")).reset_index())
    s = s[s["papeis"] >= 3].nlargest(12, "papeis").assign(mediana=lambda x: x["mediana"] * 100)
    s["setor"] = s["setor"].str.slice(0, 28)
    graficos.mostrar(graficos.barras_h(s, "setor", "mediana", " %", 1, altura=390))

# ---------------------------------------------------------------- tabela completa
with ui.card("b3_tabela"):
    ui.titulo_card("Todos os papéis", "Filtrados pela classe, setor e volume escolhidos acima · clique no cabeçalho "
                   "para ordenar")
    busca = st.text_input("Procurar", placeholder="Ticker ou empresa (ex.: PETR4, Itaú)", label_visibility="collapsed")
    t = base
    if busca.strip():
        alvo = dados._normalizar(busca)
        t = t[(t["ticker"] + " " + t["fundo"].fillna("")).map(dados._normalizar).str.contains(alvo, regex=False)]
    colunas = ["ticker", "fundo", "setor", "segmento_listagem", "fechamento", "retorno_dia", "retorno_1m",
               "retorno_ano", "retorno_12m", "volume_medio_diario"] + (["p_vp"] if classe == "FII" else [])
    t = t[colunas].sort_values("volume_medio_diario", ascending=False)
    t["segmento_listagem"] = t["segmento_listagem"].str.replace(" de Governança Corporativa", "", regex=False)
    for c in ("retorno_dia", "retorno_1m", "retorno_ano", "retorno_12m"):
        t[c] = t[c] * 100
    st.dataframe(
        t, hide_index=True, width="stretch", height=420,
        column_config={
            "ticker": st.column_config.TextColumn("Ticker", pinned=True),
            "fundo": st.column_config.TextColumn("Emissor", width="medium"),
            "setor": st.column_config.TextColumn("Setor" if classe == "Ação" else "Segmento", width="medium"),
            "segmento_listagem": st.column_config.TextColumn("Listagem"),
            "fechamento": st.column_config.NumberColumn("Fecho (R$)", format="%.2f"),
            "retorno_dia": st.column_config.NumberColumn("Dia (%)", format="%+.2f"),
            "retorno_1m": st.column_config.NumberColumn("1 mês (%)", format="%+.1f"),
            "retorno_ano": st.column_config.NumberColumn("Ano (%)", format="%+.1f"),
            "retorno_12m": st.column_config.NumberColumn("12 meses (%)", format="%+.1f"),
            "volume_medio_diario": st.column_config.NumberColumn("Volume médio (R$)", format="compact"),
            "p_vp": st.column_config.NumberColumn("P/VP", format="%.2f"),
        })

ui.rodape("Fonte: B3, séries históricas de cotações (COTAHIST), mercado à vista em lote padrão; emissores e setores "
          "do Formulário Cadastral e do cadastro de companhias da CVM; P/VP dos FII com a cota patrimonial do informe "
          "mensal da CVM. O Ibovespa não vem no COTAHIST: usa-se o ETF BOVA11, que o replica. Eventos societários são "
          "detetados pela própria série (heurística), não por um calendário oficial.")
