"""Fundos imobiliários: rankings e segmentos (CVM, informe mensal estruturado)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from painel import dados, formato, graficos, ui

k = dados.linha("fii_kpi")
ui.cabecalho("Fundos imobiliários", "Último informe mensal de cada FII negociado em bolsa (até 4 meses). DY e "
             "rentabilidade são os <b>informados à CVM</b> (sobre o património), não sobre a cotação.",
             selo=f"Referência: {k.get('mes_ref', '—')}")

rk = dados.tabela("fii_ranking")
ui.kpis([
    {"rotulo": "FII listados com informe", "valor": formato.numero(k.get("fiis")), "icone": "predio"},
    {"rotulo": "PL somado", "valor": f"R$ {formato.numero(k.get('pl_bi'), 1)} bi", "icone": "carteira"},
    {"rotulo": "Posições de cotistas", "valor": formato.numero(rk["cotistas"].sum()), "icone": "pessoas"},
    {"rotulo": "Segmentos", "valor": formato.numero(k.get("segmentos")), "icone": "camadas"},
])

# Filtros aplicados aos rankings (mesmos critérios do painel AI/BI, mas com segmento e tamanho escolhíveis).
f1, f2 = st.columns([3, 1])
segmentos = sorted(rk["segmento"].dropna().unique())
escolha = f1.multiselect("Segmentos", segmentos, placeholder="Todos os segmentos")
top_n = f2.segmented_control("Mostrar", [5, 10, 15], default=10, format_func=lambda n: f"Top {n}")
base = rk[rk["segmento"].isin(escolha)] if escolha else rk
n = top_n or 10


def topo(df: pd.DataFrame, col: str, escala: float = 1.0) -> pd.DataFrame:
    d = df.dropna(subset=[col]).nlargest(n, col)
    return d.assign(valor=d[col] * escala)


PL50, PL100 = base["pl"] >= 50e6, base["pl"] >= 100e6
rankings = [
    ("Mais cotistas", topo(base, "cotistas"), lambda v: formato.numero(v), "Posições de cotistas no último informe"),
    ("Maior património líquido", topo(base, "pl"), formato.compacto, "PL no último informe"),
    ("Maior % em caixa", topo(base[PL50], "liquidez_sobre_pl", 100), lambda v: formato.pct(v, 1),
     "Ativos de liquidez / PL · PL ≥ R$ 50 mi"),
    ("Maior DY no último mês", topo(base[PL100 & base["dy_mes"].between(0, 0.05, inclusive="right")], "dy_mes", 100),
     lambda v: formato.pct(v, 2), "PL ≥ R$ 100 mi · exclui DY > 5 %"),
    ("Maior DY em 12 meses", topo(base[PL100 & base["dy_12m"].between(0, 0.40, inclusive="right")], "dy_12m", 100),
     lambda v: formato.pct(v, 1), "PL ≥ R$ 100 mi · exclui DY > 40 %"),
    ("Maior rentabilidade em 12 meses", topo(base[PL100 & base["rentab_12m"].between(-0.9, 1.0)], "rentab_12m", 100),
     lambda v: formato.pct(v, 1, sinal=True), "Efetiva, inclui rendimentos · PL ≥ R$ 100 mi"),
]
for inicio in (0, 3):
    for i, col in enumerate(st.columns(3, gap="medium"), start=inicio):
        titulo, df, fmt, sub = rankings[i]
        with col:
            ui.ranking(df, "valor", fmt, titulo, sub, chave=f"rk_{i}")

seg = dados.tabela("fii_segmentos").sort_values("pl_bi", ascending=False)
c1, c2 = st.columns([2, 3], gap="medium")
with c1, ui.card("seg_graf"):
    ui.titulo_card("PL por segmento", "R$ bi")
    graficos.mostrar(graficos.barras_h(seg, "segmento", "pl_bi", " bi", 1, altura=360))
with c2, ui.card("seg_tab"):
    ui.titulo_card("Segmentos", "DY mediano do mês e fundos que informaram DY zero")
    st.dataframe(
        seg, hide_index=True, width="stretch", height=36 * len(seg) + 38,
        column_config={
            "segmento": st.column_config.TextColumn("Segmento"),
            "fundos": st.column_config.NumberColumn("Fundos"),
            "pl_bi": st.column_config.NumberColumn("PL (R$ bi)", format="%.1f"),
            "dy_mediano_mes_pct": st.column_config.NumberColumn("DY mediano (%)", format="%.2f"),
            "fundos_dy_zero": st.column_config.NumberColumn("DY zero"),
            "posicoes_cotistas": st.column_config.NumberColumn("Cotistas", format="localized"),
        })

ui.rodape("Fonte: CVM, informe mensal estruturado de FII. Ticker derivado do ISIN das cotas. Cotação, liquidez "
          "de pregão e P/VP estão na página Bolsa (classe FII). Valores extremos costumam ser amortizações ou erros de "
          "informe.")
