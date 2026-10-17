"""Juros, câmbio e atividade (Banco Central)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from painel import dados, formato, graficos, ui

ui.cabecalho("Mercado", "Juros, câmbio, atividade económica, índices da B3 e Tesouro Direto. Fontes: Banco Central "
             "(SGS e PTAX), B3 e Tesouro Nacional, atualizados pelo Azure Data Factory nos dias úteis.")

k = dados.linha("kpi_mercado")
ptax = dados.tabela("ptax")
ultima = ptax["data"].max()


def var_ptax(simbolo: str) -> tuple[str | None, str]:
    s = ptax[ptax["simbolo"] == simbolo].sort_values("data")
    if len(s) < 2:
        return None, ""
    v = (s["cotacao_venda"].iloc[-1] / s["cotacao_venda"].iloc[-2] - 1) * 100
    return f"{formato.pct(v, 2, sinal=True)} no dia", "pos" if v < 0 else "neg"  # real mais forte = verde


usd_nota, usd_tom = var_ptax("USD")
eur_nota, eur_tom = var_ptax("EUR")
ibc = dados.tabela("ibc").sort_values("mes")
ui.kpis([
    {"rotulo": "Meta Selic", "valor": formato.pct(k.get("meta_selic"), 2).replace(" %", " % a.a."), "icone": "juros",
     "nota": "definida pelo Copom"},
    {"rotulo": "PTAX dólar (venda)", "valor": formato.brl(k.get("ptax_usd"), 4), "icone": "cambio",
     "nota": usd_nota, "tom": usd_tom},
    {"rotulo": "PTAX euro (venda)", "valor": formato.brl(k.get("ptax_eur"), 4), "icone": "cambio",
     "nota": eur_nota, "tom": eur_tom},
    {"rotulo": "IBC-Br (índice)", "valor": formato.numero(k.get("ibc_br"), 1), "icone": "atividade",
     "nota": f"referência {formato.mes(ibc['mes'].iloc[-1])}" if len(ibc) else None},
])

PERIODOS = {"1A": 1, "3A": 3, "5A": 5, "Tudo": None}


def recortar(df: pd.DataFrame, col: str, anos: int | None) -> pd.DataFrame:
    return df if anos is None else df[df[col] >= df[col].max() - pd.DateOffset(years=anos)]


c1, c2 = st.columns(2, gap="medium")
with c1, ui.card("selic"):
    ui.titulo_card("Selic", "Meta do Copom e taxa efetiva anualizada, fim de mês (% a.a.)")
    p = st.segmented_control("Período", list(PERIODOS), default="5A", key="p_selic", label_visibility="collapsed")
    graficos.mostrar(graficos.linhas(recortar(dados.tabela("selic"), "data", PERIODOS[p or "Tudo"]), "data", "valor",
                                     "serie", " %", 2, cores_serie={"Meta Selic (Copom)": graficos.PALETA[0],
                                                                    "Selic efetiva anualizada": graficos.PALETA[1]}))
with c2, ui.card("ptax"):
    ui.titulo_card("PTAX de venda", f"Reais por unidade de moeda estrangeira · última cotação {formato.data(ultima)}")
    a, b = st.columns([2, 3])
    moedas = a.pills("Moedas", ["USD", "EUR", "GBP"], default=["USD", "EUR"], selection_mode="multi", key="m_ptax",
                     label_visibility="collapsed")
    p = b.segmented_control("Período", list(PERIODOS), default="1A", key="p_ptax", label_visibility="collapsed")
    sel = ptax[ptax["simbolo"].isin(moedas or ["USD"])]
    graficos.mostrar(graficos.linhas(recortar(sel, "data", PERIODOS[p or "Tudo"]), "data", "cotacao_venda", "simbolo",
                                     "", 4))

c3, c4 = st.columns(2, gap="medium")
with c3, ui.card("cambio"):
    ui.titulo_card("Variação mensal do câmbio", "PTAX de fim de mês face ao mês anterior, últimos 12 meses (%)")
    cm = dados.tabela("cambio_mensal").sort_values(["simbolo", "mes"])
    moeda = st.segmented_control("Moeda", sorted(cm["simbolo"].unique()), default="USD", key="m_cambio",
                                 label_visibility="collapsed")
    graficos.mostrar(graficos.barras_sinal(cm[cm["simbolo"] == (moeda or "USD")], "mes", "variacao_pct", " %", 2,
                                           altura=268))
with c4, ui.card("ibc"):
    ui.titulo_card("IBC-Br", "Índice de atividade económica do Banco Central, mensal (desde 2015)")
    graficos.mostrar(graficos.linhas(ibc, "mes", "ibc_br", None, "", 1, altura=310, area=True))

linhas_snapshot = dados.meta().get("linhas", {})
if "indices_b3" in linhas_snapshot:
    ind = dados.tabela("indices_b3").sort_values("data")
    c5, c6 = st.columns([3, 2], gap="medium")
    with c5, ui.card("indices"):
        ui.titulo_card("Índices da B3", "Índices oficiais de retorno total (proventos reinvestidos), base 100 no início "
                       f"do período · último fecho {formato.data(ind['data'].max())}")
        a, b = st.columns([3, 2])
        nomes = dict(zip(ind["indice"], ind["nome_indice"]))
        escolha = a.pills("Índices", list(nomes), default=["IBOV", "IFIX"], selection_mode="multi", key="m_indices",
                          format_func=lambda x: f"{x} · {nomes[x]}" if x != "IBOV" else "IBOV · Ibovespa",
                          label_visibility="collapsed") or ["IBOV"]
        p = b.segmented_control("Período", list(PERIODOS), default="3A", key="p_indices", label_visibility="collapsed")
        s = recortar(ind[ind["indice"].isin(escolha)], "data", PERIODOS[p or "Tudo"]).copy()
        s["base100"] = s.groupby("indice")["fechamento"].transform(lambda x: x / x.iloc[0] * 100)
        graficos.mostrar(graficos.linhas(s, "data", "base100", "indice", "", 1, altura=300))
    with c6, ui.card("indices_tabela"):
        ui.titulo_card("Rentabilidade dos índices", "Variação do fecho (%)")
        ult = ind["data"].max()
        linhas = []
        for cod, g_ in ind.groupby("indice"):
            g_ = g_.set_index("data")["fechamento"]
            def var(desde):  # noqa: E306
                base = g_[g_.index <= desde]
                return (g_.iloc[-1] / base.iloc[-1] - 1) * 100 if len(base) else float("nan")
            linhas.append({"Índice": f"{cod} · {nomes[cod]}", "Pontos": g_.iloc[-1],
                           "Dia": (g_.iloc[-1] / g_.iloc[-2] - 1) * 100 if len(g_) > 1 else float("nan"),
                           "No ano": var(pd.Timestamp(ult.year - 1, 12, 31)),
                           "12 meses": var(ult - pd.DateOffset(years=1)), "5 anos": var(ult - pd.DateOffset(years=5))})
        st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch",
                     column_config={"Pontos": st.column_config.NumberColumn(format="%.0f"),
                                    **{c: st.column_config.NumberColumn(format="%+.1f")
                                       for c in ("Dia", "No ano", "12 meses", "5 anos")}})

if "tesouro" in linhas_snapshot:
    td = dados.tabela("tesouro")
    td["vencimento"] = pd.to_datetime(td["vencimento"])
    hoje_td = td["data"].max()
    atuais = td[(td["data"] == hoje_td) & (td["taxa_compra"] > 0)].sort_values(["indexador", "vencimento"])
    c7, c8 = st.columns([2, 3], gap="medium")
    with c7, ui.card("tesouro_hoje"):
        ui.titulo_card("Tesouro Direto: taxas de compra", f"Títulos à venda em {formato.data(hoje_td)} · % ao ano "
                       "(acima do IPCA nos IPCA+, acima da Selic no Tesouro Selic)")
        st.dataframe(atuais[["titulo", "vencimento", "taxa_compra", "pu_compra"]], hide_index=True, width="stretch",
                     height=330, column_config={
                         "titulo": st.column_config.TextColumn("Título", width="medium"),
                         "vencimento": st.column_config.DateColumn("Vencimento", format="DD/MM/YYYY"),
                         "taxa_compra": st.column_config.NumberColumn("Taxa (% a.a.)", format="%.2f"),
                         "pu_compra": st.column_config.NumberColumn("Preço (R$)", format="%.2f")})
    with c8, ui.card("tesouro_hist"):
        ui.titulo_card("Evolução das taxas", "Taxa de compra de cada título ao longo do tempo (% a.a.)")
        a, b = st.columns([3, 2])
        opcoes = list(atuais["titulo"]) or sorted(td["titulo"].unique())
        padrao = [t for t in opcoes if t.startswith(("Tesouro IPCA+ 20", "Tesouro Prefixado 20"))
                  and "Juros" not in t][:2] or opcoes[:1]
        titulos = a.multiselect("Títulos", opcoes, default=padrao, key="m_tesouro", label_visibility="collapsed")
        p = b.segmented_control("Período", list(PERIODOS), default="3A", key="p_tesouro", label_visibility="collapsed")
        h = td[td["titulo"].isin(titulos or padrao) & (td["taxa_compra"] > 0)]
        graficos.mostrar(graficos.linhas(recortar(h, "data", PERIODOS[p or "Tudo"]), "data", "taxa_compra", "titulo",
                                         " %", 2, altura=300))

ui.rodape("Fontes: Banco Central do Brasil, SGS (séries 432, 1178, 4390, 24363) e PTAX; B3 (índices oficiais, "
          "estatísticas diárias); Tesouro Nacional (Tesouro Transparente, preços e taxas do Tesouro Direto).")
