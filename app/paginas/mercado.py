"""Juros, câmbio e atividade (Banco Central)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from painel import dados, formato, graficos, ui

ui.cabecalho("Mercado", "Juros, câmbio e atividade económica. Fonte: Banco Central do Brasil (SGS e PTAX), "
             "atualizado pelo Azure Data Factory nos dias úteis.")

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

ui.rodape("Fonte: Banco Central do Brasil, SGS (séries 432, 1178, 4390, 24363) e PTAX.")
