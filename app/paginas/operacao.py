"""Operação da plataforma: reconciliação com as fontes, frescura, execuções e qualidade de dados."""
from __future__ import annotations

import streamlit as st

from painel import dados, formato, ui

ui.cabecalho("Operação e qualidade", "Última reconciliação com as fontes oficiais, frescura dos dados, execuções e "
             "regras de qualidade que falharam nos últimos 14 dias.")

rec = dados.tabela("reconciliacao")
fresc = dados.tabela("frescura")
execs = dados.tabela("execucoes")
dq = dados.tabela("qualidade")
NOMES = {"bcb_sgs": "BCB · séries (SGS)", "bcb_ptax": "BCB · PTAX", "cvm": "CVM · fundos"}

falhas = int((execs["estado"] == "FAILED").sum())
atrasadas = int((fresc["dias"] > 4).sum())
ui.kpis([
    {"rotulo": "Fontes reconciliadas sem divergências", "valor": f"{int((rec['divergencias'] == 0).sum())} de {len(rec)}",
     "icone": "check", "nota": f"{formato.numero(rec['registos_fonte'].sum())} registos comparados"},
    {"rotulo": "Entidades com dados há mais de 4 dias", "valor": str(atrasadas), "icone": "calendario",
     "nota": "normal nas séries e informes mensais (ex.: IBC-Br, FII)"},
    {"rotulo": "Execuções com falha (14 dias)", "valor": str(falhas), "icone": "atividade",
     "tom": "neg" if falhas else "pos", "nota": f"{formato.numero(execs['execucoes'].sum())} execuções no total"},
    {"rotulo": "Regras de qualidade com falhas", "valor": str(len(dq)), "icone": "camadas",
     "nota": f"{int(dq['severidade'].isin(['CRITICAL', 'HIGH']).sum())} bloqueantes (CRITICAL/HIGH)"},
])

c1, c2 = st.columns([1, 1], gap="medium")
with c1, ui.card("rec"):
    ui.titulo_card("Reconciliação com a fonte", "Última execução por fonte, todas as entidades e períodos")
    linhas = []
    for r in rec.sort_values("fonte").itertuples(index=False):
        tom = "ok" if r.divergencias == 0 else "falha"
        linhas.append(
            f"<tr><td><b>{NOMES.get(r.fonte, r.fonte)}</b><br><small>{formato.numero(r.entidades)} entidades · "
            f"{formato.numero(r.registos_fonte)} registos</small></td>"
            f"<td>{ui.estado(r.resultado, tom)}</td><td style='text-align:right'>{formato.numero(r.divergencias)}"
            f"<br><small>divergências</small></td><td style='text-align:right'><small>{formato.data_hora(r.quando)}"
            "</small></td></tr>")
    ui.html("<table style='width:100%;border-collapse:collapse;font-size:.85rem'>" + "".join(linhas) + "</table>")
with c2, ui.card("fresc"):
    ui.titulo_card("Frescura", "Última data de referência carregada por entidade (watermark)")
    st.dataframe(
        fresc.sort_values(["dias", "fonte"], ascending=[False, True]), hide_index=True, width="stretch", height=260,
        column_config={
            "fonte": st.column_config.TextColumn("Fonte"), "entidade": st.column_config.TextColumn("Entidade"),
            "ultima_data": st.column_config.TextColumn("Última data"),
            "dias": st.column_config.NumberColumn("Dias", help="Dias desde a última data de referência"),
            "reconciliado": st.column_config.DatetimeColumn("Reconciliado em", format="DD/MM/YYYY HH:mm"),
        })

with ui.card("execs"):
    ui.titulo_card("Execuções", "Últimos 14 dias, por dia, pipeline e estado")
    st.dataframe(
        execs.sort_values(["dia", "pipeline"], ascending=[False, True]), hide_index=True, width="stretch",
        column_config={
            "dia": st.column_config.DateColumn("Dia", format="DD/MM/YYYY"),
            "pipeline": st.column_config.TextColumn("Pipeline"), "estado": st.column_config.TextColumn("Estado"),
            "execucoes": st.column_config.NumberColumn("Execuções"),
            "lidos": st.column_config.NumberColumn("Lidos", format="localized"),
            "escritos": st.column_config.NumberColumn("Escritos", format="localized"),
            "rejeitados": st.column_config.NumberColumn("Rejeitados", format="localized"),
            "duracao_media_s": st.column_config.NumberColumn("Duração média (s)", format="%.1f"),
        })

with ui.card("dq"):
    ui.titulo_card("Regras de qualidade com falhas", "INFO só regista; CRITICAL e HIGH bloqueiam a publicação na gold")
    st.dataframe(
        dq.sort_values("ultima", ascending=False), hide_index=True, width="stretch",
        column_config={
            "ultima": st.column_config.DatetimeColumn("Última", format="DD/MM/YYYY HH:mm"),
            "tabela": st.column_config.TextColumn("Tabela", width="large"), "regra": st.column_config.TextColumn("Regra"),
            "severidade": st.column_config.TextColumn("Severidade"),
            "registos_falhados": st.column_config.NumberColumn("Registos", format="localized"),
        })

ui.rodape("Fonte: tabelas de controlo da plataforma (findata_dev.control) e vistas de operação da gold.")
