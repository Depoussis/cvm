"""Painel Findata em Streamlit: mercado (BCB), fundos (CVM), FII, análise de fundo e operação.

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
                   initial_sidebar_state="expanded")
aplicar_estilo()
st.logo(str(Path(__file__).parent / "logo.svg"), size="large")

pagina = st.navigation([
    st.Page("paginas/mercado.py", title="Mercado", icon=":material/trending_up:", default=True),
    st.Page("paginas/fundos.py", title="Fundos", icon=":material/account_balance:"),
    st.Page("paginas/fii.py", title="Fundos imobiliários", icon=":material/apartment:"),
    st.Page("paginas/analise.py", title="Análise de fundo", icon=":material/query_stats:"),
    st.Page("paginas/operacao.py", title="Operação e qualidade", icon=":material/fact_check:"),
])

with st.sidebar:
    m = dados.meta()
    quando = formato.data_hora(pd.Timestamp(m["exportado_em"])) if m.get("exportado_em") else "—"
    html(f'<div class="snapshot">Atualizado em <b>{escape(quando)}</b><br>'
         "Fontes: Banco Central (SGS, PTAX) e CVM (informes diário e mensal).</div>")
    st.divider()
    st.caption("Projeto de estudo: plataforma medallion em Azure Databricks. Tema claro/escuro: menu ⋮ → Settings.")

pagina.run()
