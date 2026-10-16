"""Bolsa (B3): ações, FII e ETF do mercado à vista, a partir das séries históricas COTAHIST."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from painel import dados, formato, graficos, ui

d = dados.tabela("b3_desempenho")
cot = dados.tabela("b3_cotacoes")
pregao = pd.Timestamp(d["data_referencia"].max())
ui.cabecalho("Bolsa", "Ações, fundos imobiliários e ETF do mercado à vista da B3 (séries históricas COTAHIST). "
             "Retornos de <b>preço</b>, ajustados a desdobramentos, grupamentos e bonificações (eventos oficiais da B3); "
             "os dividendos aparecem à parte (DY e histórico anual).",
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
# fundamentos das ações na data mais recente (DFP/ITR da CVM, calculados pelo job do modelo)
fund = dados.tabela("ml_ranking")[["ticker", "earnings_yield", "book_to_market", "roe"]]
base = base.merge(fund, on="ticker", how="left")
base["p_l"] = (1 / base["earnings_yield"]).where(base["earnings_yield"] > 0)
base["p_vp_acao"] = (1 / base["book_to_market"]).where(base["book_to_market"] > 0)


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
    rankings.append(("Maior dividend yield (12 meses)", topo("dy_12m", filtro=base["dy_12m"].between(0, 0.30)),
                     lambda v: formato.pct(v, 1), "Proventos com data com nos últimos 12 meses / preço · exclui > 30 %"))
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
               "retorno_ano", "retorno_12m", "volume_medio_diario"] + (
        ["p_vp"] if classe == "FII" else ["dy_12m", "p_l", "p_vp_acao", "roe"] if classe == "Ação" else [])
    t = t[colunas].sort_values("volume_medio_diario", ascending=False)
    t["segmento_listagem"] = t["segmento_listagem"].str.replace(" de Governança Corporativa", "", regex=False)
    for c in ("retorno_dia", "retorno_1m", "retorno_ano", "retorno_12m", "dy_12m", "roe"):
        if c in t:
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
            "dy_12m": st.column_config.NumberColumn("DY 12m (%)", format="%.1f"),
            "p_l": st.column_config.NumberColumn("P/L", format="%.1f", help="Valor de mercado / lucro 12 meses (vazio se prejuízo)"),
            "p_vp_acao": st.column_config.NumberColumn("P/VP", format="%.2f", help="Valor de mercado / património líquido"),
            "roe": st.column_config.NumberColumn("ROE (%)", format="%.1f", help="Lucro 12 meses / património líquido"),
        })

# ---------------------------------------------------------------- dividendos por ano
divs = dados.tabela("b3_dividendos")
com_div = [t_ for t_ in rotulos if t_ in set(divs["ticker"])]
if com_div:
    with ui.card("b3_dividendos"):
        ui.titulo_card("Dividendos e JCP por ano", "Soma por ação (ajustada a desdobramentos) e dividend yield do ano "
                       "(soma de cada provento / fecho na data com)")
        escolhido = st.selectbox("Ação", com_div, index=com_div.index("PETR4") if "PETR4" in com_div else 0,
                                 format_func=rotulos.get, key="b3_div_ticker", label_visibility="collapsed")
        h = divs[divs["ticker"] == escolhido].sort_values("ano")
        g1, g2 = st.columns([3, 2], gap="medium")
        with g1:
            graficos.mostrar(graficos.barras(h.assign(ano=h["ano"].astype(str)), "ano", "valor_ajustado_ano",
                                             "R$ por ação", 2, altura=280))
        with g2:
            st.dataframe(
                h.sort_values("ano", ascending=False).assign(dy_ano=h["dy_ano"] * 100),
                hide_index=True, width="stretch", height=280,
                column_config={"ticker": None,
                               "ano": st.column_config.NumberColumn("Ano", format="%d"),
                               "eventos": st.column_config.NumberColumn("Eventos"),
                               "valor_ajustado_ano": st.column_config.NumberColumn("R$/ação", format="%.4f"),
                               "jcp_ajustado_ano": st.column_config.NumberColumn("dos quais JCP", format="%.4f"),
                               "dy_ano": st.column_config.NumberColumn("DY (%)", format="%.2f")})

ui.rodape("Fonte: B3, séries históricas de cotações (COTAHIST), mercado à vista em lote padrão, e proventos (site da "
          "B3, empresas listadas); emissores e setores do Formulário Cadastral e do cadastro de companhias da CVM; "
          "P/L, P/VP e ROE das demonstrações DFP/ITR da CVM (último trimestre entregue); P/VP dos FII com a cota "
          "patrimonial do informe mensal. O Ibovespa não vem no COTAHIST: usa-se o ETF BOVA11. Desdobramentos e bonificações "
          "oficiais da B3 nas ações; em FII e ETF são detetados pela própria série.")
