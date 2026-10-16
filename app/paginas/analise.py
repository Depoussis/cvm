"""Análise de um fundo: FI (informe diário, agregado por mês) ou FII (informe mensal), comparado com a Selic."""
from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from painel import dados, formato, graficos, ui

ui.cabecalho("Análise de fundo", "Escolhe um fundo de investimento (FI) ou imobiliário (FII). A rentabilidade do FII é "
             "a efetiva do mês (inclui rendimentos). Ambos comparam com a Selic acumulada no mês; meses incompletos "
             "ficam de fora.")

cat = dados.catalogo_fundos()
b1, b2 = st.columns([1, 3])
tipo = b1.segmented_control("Tipo", ["Todos", "FII", "FI"], default="Todos", key="tipo_fundo")
termo = b2.text_input("Pesquisar", placeholder="Nome, ticker ou CNPJ (ex.: KNCR11, Kinea, 12.005.956)",
                      key="busca_fundo")
filtrado = cat if tipo in (None, "Todos") else cat[cat["tipo"] == tipo]
filtrado = dados.buscar(filtrado, termo)
if filtrado.empty:
    st.info("Nenhum fundo encontrado. Tenta parte do nome, o ticker ou o CNPJ.")
    st.stop()
opcoes = filtrado.head(300)
padrao = dados.fundo_padrao(cat)
indice = list(opcoes.index).index(padrao) if padrao in opcoes.index and not termo and tipo in (None, "Todos") else 0
escolhido = st.selectbox(
    f"Fundo ({formato.numero(len(filtrado))} encontrados, ordenados por PL"
    + ("; mostra os 300 maiores" if len(filtrado) > 300 else "") + ")",
    opcoes.index, index=indice, format_func=lambda i: opcoes.at[i, "rotulo"], key="fundo_sel")
f = cat.loc[escolhido]

selic = dados.tabela("selic_mes").rename(columns={"selic_mes_pct": "selic"})
mes_fechado = pd.Timestamp.today().normalize().replace(day=1)
if f["tipo"] == "FII":
    h = dados.tabela("fii_mensal")
    h = h[h["cnpj"] == f["cnpj"]].sort_values("mes").assign(
        rentab=lambda d: d["rentab_efetiva_mes"] * 100, dy=lambda d: d["dividend_yield_mes"] * 100)
else:
    h = dados.tabela("fundos_mensal")
    h = h[h["cnpj"] == f["cnpj"]].sort_values("mes").assign(rentab=lambda d: d["rentab_mes"] * 100)
h = h[h["mes"] < mes_fechado].merge(selic, on="mes", how="left")
ult = h.iloc[-1] if len(h) else pd.Series(dtype=object)

# Ficha
chips = [f'<span class="chip acento">{escape(f["tipo"])}</span>']
if isinstance(f["ticker"], str) and f["ticker"]:
    chips.append(f'<span class="chip acento">{escape(f["ticker"])}</span>')
chips += [f'<span class="chip">{escape(str(v))}</span>' for v in
          (dados.formatar_cnpj(f["cnpj"]), f["classificacao"], f["administrador"]) if isinstance(v, str) and v]
with ui.card("ficha"):
    ui.html(
        f'<div class="ficha"><div><div class="nome">{escape(f["nome"])}</div><div class="chips">{"".join(chips)}</div></div>'
        f'<div class="numeros"><div><b>{formato.compacto(ult.get("pl"))}</b><small>PL em {formato.mes(ult.get("mes"))}</small></div>'
        f'<div><b>{formato.numero(ult.get("cotistas"))}</b><small>cotistas</small></div></div></div>')

if h.empty:
    st.info("Este fundo não tem meses fechados no snapshot.")
    st.stop()

# Indicadores do período disponível
doze = h.tail(12)
acum = lambda s: ((1 + s.fillna(0) / 100).prod() - 1) * 100  # noqa: E731
r12, s12 = acum(doze["rentab"]), acum(doze["selic"])
acima = (doze["rentab"] > doze["selic"]).sum()
itens = [
    {"rotulo": f"Rentabilidade em {len(doze)} meses", "valor": formato.pct(r12, 2, sinal=True), "icone": "atividade",
     "nota": f"Selic no mesmo período: {formato.pct(s12, 2)}", "tom": "pos" if r12 >= s12 else "neg"},
    {"rotulo": "Meses acima da Selic", "valor": f"{acima} de {len(doze)}", "icone": "check"},
    {"rotulo": "Último mês", "valor": formato.pct(ult.get("rentab"), 2, sinal=True), "icone": "calendario",
     "nota": f"{formato.mes(ult.get('mes'))} · Selic {formato.pct(ult.get('selic'), 2)}"},
]
if f["tipo"] == "FII":
    dy12 = doze["dy"].sum()
    itens.append({"rotulo": "DY somado em 12 meses", "valor": formato.pct(dy12, 2), "icone": "carteira",
                  "nota": f"último mês {formato.pct(ult.get('dy'), 2)}"})
else:
    cap = doze["captacao_liquida"].sum()
    itens.append({"rotulo": "Captação líquida em 12 meses", "valor": formato.compacto(cap), "icone": "fluxo",
                  "tom": "pos" if cap >= 0 else "neg", "nota": "entradas menos resgates"})
ui.kpis(itens)

c1, c2 = st.columns(2, gap="medium")
with c1, ui.card("rentab"):
    ui.titulo_card("Rentabilidade no mês vs Selic", "% no mês; barras vermelhas = mês negativo")
    graficos.mostrar(graficos.barras_e_linha(h, "mes", "rentab", "selic", "Fundo", "Selic do mês"))
with c2, ui.card("acumulada"):
    ui.titulo_card("Rentabilidade acumulada", f"% desde {formato.mes(h['mes'].iloc[0])}, fundo vs Selic")
    a = h[["mes"]].assign(Fundo=((1 + h["rentab"].fillna(0) / 100).cumprod() - 1) * 100,
                          Selic=((1 + h["selic"].fillna(0) / 100).cumprod() - 1) * 100)
    a = a.melt("mes", var_name="serie", value_name="valor")
    graficos.mostrar(graficos.linhas(a, "mes", "valor", "serie", " %", 2,
                                     cores_serie={"Fundo": graficos.PALETA[0], "Selic": graficos.PALETA[2]}))

c3, c4 = st.columns(2, gap="medium")
with c3, ui.card("pl"):
    ui.titulo_card("Património líquido", "R$ mi, fim de mês")
    graficos.mostrar(graficos.linhas(h.assign(pl_mi=h["pl"] / 1e6), "mes", "pl_mi", None, " mi", 1, area=True))
with c4:
    if f["tipo"] == "FII":
        with ui.card("dy"):
            ui.titulo_card("Dividend yield no mês", "% sobre o património (informado à CVM)")
            graficos.mostrar(graficos.barras_sinal(h, "mes", "dy", " %", 2))
    else:
        with ui.card("cotistas"):
            ui.titulo_card("Cotistas", "Fim de mês")
            graficos.mostrar(graficos.linhas(h, "mes", "cotistas", None, "", 0, area=True))

ui.rodape("Fonte: CVM (informe diário de FI agregado por mês na camada gold; informe mensal de FII) e Banco Central "
          "(SGS 4390, Selic acumulada no mês).")
