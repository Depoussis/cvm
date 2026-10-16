"""Indústria de fundos de investimento (CVM, informe diário)."""
from __future__ import annotations

import streamlit as st

from painel import dados, formato, graficos, ui

k = dados.linha("kpi_fundos")
ui.cabecalho("Fundos de investimento", "Classes de fundos com informe diário na CVM (sem subclasses). Rentabilidade = "
             "variação da cota de fim de mês; só fundos com PL ≥ R$ 10 mi.",
             selo=f"Último mês fechado: {formato.mes(k.get('mes'))}")
ui.aviso("<b>PL e captação somados incluem fundos de cotas (FIC)</b>, que aplicam noutros fundos: há dupla contagem, "
         "por isso não são o património da indústria.")

capt = k.get("captacao_liquida_bi")
ui.kpis([
    {"rotulo": "PL somado", "valor": f"R$ {formato.numero(k.get('pl_total_bi'), 0)} bi", "icone": "carteira",
     "nota": "com dupla contagem FIC"},
    {"rotulo": "Fundos/classes com informe", "valor": formato.numero(k.get("fundos")), "icone": "fundos"},
    {"rotulo": "Captação líquida no mês", "valor": f"R$ {formato.numero(capt, 1)} bi", "icone": "fluxo",
     "nota": "entradas menos resgates", "tom": "pos" if (capt or 0) >= 0 else "neg"},
    {"rotulo": "Posições de cotistas", "valor": formato.numero(k.get("cotistas")), "icone": "pessoas",
     "nota": "um investidor conta uma vez por fundo"},
])

ind = dados.tabela("industria").sort_values("mes")
c1, c2 = st.columns(2, gap="medium")
with c1, ui.card("pl"):
    ui.titulo_card("Património líquido somado", "R$ bi, fim de mês")
    graficos.mostrar(graficos.linhas(ind, "mes", "pl_total_bi", None, " bi", 0, area=True))
with c2, ui.card("captacao"):
    ui.titulo_card("Captação líquida por mês", "R$ bi; verde = entradas superam resgates")
    graficos.mostrar(graficos.barras_sinal(ind, "mes", "captacao_liquida_bi", " bi", 1))

vs = dados.tabela("vs_selic").sort_values("mes")
c3, c4 = st.columns(2, gap="medium")
with c3, ui.card("vs_selic"):
    ui.titulo_card("Fundos que bateram a Selic", "% dos fundos de cada classificação com rentabilidade acima da Selic "
                   "acumulada no mês (SGS 4390)")
    graficos.mostrar(graficos.linhas(vs, "mes", "pct_acima_selic", "classificacao", " %", 1))
with c4, ui.card("mediana"):
    ui.titulo_card("Rentabilidade mediana no mês", "% por classificação")
    graficos.mostrar(graficos.linhas(vs, "mes", "rentab_mediana_pct", "classificacao", " %", 2))

top = dados.tabela("top_pl")
with ui.card("top"):
    ui.titulo_card("20 maiores fundos por património líquido", f"Posição em {formato.data(top['data'].max())}")
    st.dataframe(
        top[["posicao", "fundo", "classificacao", "administrador", "pl_bi", "cotistas"]],
        hide_index=True, width="stretch", height=36 * len(top) + 38,
        column_config={
            "posicao": st.column_config.NumberColumn("#", width=40),
            "fundo": st.column_config.TextColumn("Fundo", width="large"),
            "classificacao": st.column_config.TextColumn("Classificação"),
            "administrador": st.column_config.TextColumn("Administrador", width="medium"),
            "pl_bi": st.column_config.ProgressColumn("PL (R$ bi)", format="%.1f", min_value=0,
                                                     max_value=float(top["pl_bi"].max())),
            "cotistas": st.column_config.NumberColumn("Cotistas", format="localized"),
        })

ui.rodape("Fonte: CVM, informe diário de fundos de investimento (dados.cvm.gov.br).")
