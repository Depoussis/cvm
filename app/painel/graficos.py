"""Gráficos Plotly com o estilo clean do painel: linhas finas, grelha discreta, sem barra de ferramentas."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from painel import formato

FONTE = "Inter, Segoe UI, system-ui, sans-serif"
# Categóricas: acento índigo primeiro, depois tons distintos com contraste nos dois temas.
PALETA = ["#4F46E5", "#0EA5E9", "#F59E0B", "#10B981", "#EC4899", "#8B5CF6", "#64748B"]
TEMA = {
    "claro": {"texto": "#111827", "suave": "#6B7280", "grade": "#EEF0F4", "card": "#FFFFFF", "borda": "#E6E8EE",
              "positivo": "#10B981", "negativo": "#EF4444"},
    "escuro": {"texto": "#E8EAF0", "suave": "#9AA1B2", "grade": "#232633", "card": "#171A23", "borda": "#262A36",
               "positivo": "#34D399", "negativo": "#F87171"},
}
CONFIG = {"displayModeBar": False, "locale": "pt-BR"}


def cores() -> dict:
    return TEMA[st.session_state.get("tema", "claro")]


def layout(fig: go.Figure, altura: int = 300, legenda: bool = True) -> go.Figure:
    c = cores()
    fig.update_layout(
        # margens explícitas: dentro do Streamlit o automargin não chega a expandir e os rótulos ficavam cortados
        height=altura, margin=dict(l=56, r=12, t=8 if not legenda else 30, b=30), separators=",.",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONTE, size=12, color=c["texto"]), showlegend=legenda,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, title=None, font=dict(size=11, color=c["suave"])),
        hovermode="x unified",
        hoverlabel=dict(bgcolor=c["card"], bordercolor=c["borda"], font=dict(family=FONTE, size=12, color=c["texto"])),
        bargap=0.35,
    )
    fig.update_xaxes(showgrid=False, linecolor=c["borda"], tickfont=dict(color=c["suave"], size=11), title=None,
                     ticks="", zeroline=False, automargin=True)
    fig.update_yaxes(gridcolor=c["grade"], tickfont=dict(color=c["suave"], size=11), title=None, zeroline=False,
                     linecolor="rgba(0,0,0,0)", automargin=True, separatethousands=True)
    fig.update_traces(marker_cornerradius=3, selector=dict(type="bar"))
    # datas numéricas (o Plotly só traz nomes de meses em inglês) e números sem sufixos SI ("14k")
    # (ignorados nos eixos de categorias)
    fig.update_xaxes(tickformat="%m/%Y", hoverformat="%d/%m/%Y")
    fig.update_yaxes(tickformat=",.4~f")
    return fig


def mostrar(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch", config=CONFIG, theme=None)


def linhas(df: pd.DataFrame, x: str, y: str, serie: str | None = None, sufixo: str = "", casas: int = 2,
           altura: int = 300, area: bool = False, cores_serie: dict | None = None) -> go.Figure:
    fig = go.Figure()
    grupos = [(None, df)] if serie is None else list(df.groupby(serie, sort=False))
    for i, (nome, g) in enumerate(grupos):
        g = g.sort_values(x)
        cor = (cores_serie or {}).get(nome, PALETA[i % len(PALETA)])
        fig.add_trace(go.Scatter(
            x=g[x], y=g[y], name=str(nome) if nome is not None else y, mode="lines",
            line=dict(color=cor, width=2), fill="tozeroy" if area and serie is None else None,
            fillcolor=_alfa(cor, 0.08) if area and serie is None else None,
            hovertemplate=f"%{{y:,.{casas}f}}{sufixo}<extra>{nome if nome is not None else ''}</extra>"))
    if sufixo.strip():
        fig.update_yaxes(ticksuffix=sufixo)
    return layout(fig, altura, legenda=serie is not None)


def barras_sinal(df: pd.DataFrame, x: str, y: str, sufixo: str = "", casas: int = 2, altura: int = 300) -> go.Figure:
    """Barras verdes (positivas) e vermelhas (negativas), ex.: captação líquida."""
    c = cores()
    fig = go.Figure(go.Bar(
        x=df[x], y=df[y], marker_color=[c["positivo"] if v >= 0 else c["negativo"] for v in df[y].fillna(0)],
        hovertemplate=f"%{{y:,.{casas}f}}{sufixo}<extra></extra>"))
    fig.update_yaxes(ticksuffix=sufixo)
    return layout(fig, altura, legenda=False)


def barras(df: pd.DataFrame, x: str, y: str, rotulo: str = "", casas: int = 2, altura: int = 300) -> go.Figure:
    """Barras verticais numa só cor (ex.: dividendos por ano)."""
    fig = go.Figure(go.Bar(x=df[x], y=df[y], marker_color=PALETA[0], name=rotulo,
                           hovertemplate=f"<b>%{{x}}</b><br>%{{y:,.{casas}f}} {rotulo}<extra></extra>"))
    fig = layout(fig, altura, legenda=False)
    fig.update_xaxes(tickformat=None, hoverformat=None, type="category")
    return fig


def barras_h(df: pd.DataFrame, y: str, x: str, sufixo: str = "", casas: int = 1, altura: int = 320) -> go.Figure:
    d = df.sort_values(x)
    fig = go.Figure(go.Bar(
        y=d[y], x=d[x], orientation="h", marker_color=PALETA[0], text=[formato.numero(v, casas) + sufixo for v in d[x]],
        textposition="outside", cliponaxis=False, textfont=dict(size=11, color=cores()["suave"]),
        hovertemplate=f"<b>%{{y}}</b><br>%{{x:,.{casas}f}}{sufixo}<extra></extra>"))
    fig.update_xaxes(showticklabels=False, showgrid=False)
    fig.update_yaxes(showgrid=False)
    fig = layout(fig, altura, legenda=False)
    fig.update_layout(hovermode="closest", margin=dict(l=110, r=48, b=8))
    fig.update_xaxes(tickformat=None, hoverformat=None)  # eixo x numérico aqui
    fig.update_yaxes(tickformat=None)
    return fig


def barras_e_linha(df: pd.DataFrame, x: str, barra: str, linha: str, nome_barra: str, nome_linha: str,
                   sufixo: str = " %", altura: int = 300) -> go.Figure:
    """Barras (ex.: rentabilidade do fundo no mês) com linha de referência (ex.: Selic do mês)."""
    c = cores()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df[x], y=df[barra], name=nome_barra,
                         marker_color=[PALETA[0] if (v or 0) >= 0 else c["negativo"] for v in df[barra]],
                         hovertemplate=f"%{{y:,.2f}}{sufixo}<extra>{nome_barra}</extra>"))
    fig.add_trace(go.Scatter(x=df[x], y=df[linha], name=nome_linha, mode="lines",
                             line=dict(color=PALETA[2], width=2, shape="hv"),
                             hovertemplate=f"%{{y:,.2f}}{sufixo}<extra>{nome_linha}</extra>"))
    fig.update_yaxes(ticksuffix=sufixo)
    return layout(fig, altura)


def _alfa(hexa: str, a: float) -> str:
    h = hexa.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{a})"
