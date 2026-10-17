"""Painel Findata em Streamlit: mercado (BCB), bolsa (B3), fundos (CVM), FII, análise de fundo e operação.

Local:  streamlit run app/streamlit_app.py   (na raiz do repositório, para usar .streamlit/config.toml)
Os dados vêm do snapshot em app/dados/ (scripts/exportar_painel.py); a app não acede ao Databricks.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from painel import dados, formato
from painel.ui import aplicar_estilo, html

st.set_page_config(page_title="Findata · Mercado e fundos", page_icon=":material/monitoring:", layout="wide",
                   initial_sidebar_state="collapsed")
aplicar_estilo()
st.logo(str(Path(__file__).parent / "logo.svg"), size="large")

# Navegação no topo: páginas soltas e grupos (os grupos abrem um menu com as páginas)
pagina = st.navigation({
    "": [
        st.Page("paginas/mercado.py", title="Mercado", icon=":material/trending_up:", default=True),
        st.Page("paginas/acoes.py", title="Bolsa", icon=":material/candlestick_chart:"),
        st.Page("paginas/modelo.py", title="Modelo", icon=":material/model_training:"),
    ],
    "Simulador": [
        st.Page("paginas/simulador.py", title="Um papel", icon=":material/calculate:"),
        st.Page("paginas/carteira.py", title="Carteira com aportes", icon=":material/pie_chart:"),
    ],
    "Fundos": [
        st.Page("paginas/fundos.py", title="Fundos de investimento", icon=":material/account_balance:"),
        st.Page("paginas/fii.py", title="Fundos imobiliários", icon=":material/apartment:"),
        st.Page("paginas/analise.py", title="Análise de fundo", icon=":material/query_stats:"),
    ],
    "Plataforma": [
        st.Page("paginas/operacao.py", title="Operação e qualidade", icon=":material/fact_check:"),
    ],
}, position="top")

m = dados.meta()
quando = formato.data_hora(pd.Timestamp(m["exportado_em"])) if m.get("exportado_em") else "—"
html(f'<div class="faixa-snapshot">Atualizado em <b>{escape(quando)}</b> · Fontes: Banco Central (SGS, PTAX), '
     "B3 (cotações, proventos e índices), CVM (informes, cadastros, DFP/ITR) e Tesouro Direto · Projeto de estudo · "
     "Tema claro/escuro: menu ⋮ → Settings</div>")

pagina.run()
