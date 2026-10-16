"""Simulador: quanto teria hoje quem comprou uma ação ou um FII numa data, com eventos e proventos."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from painel import dados, formato, graficos, simulador, ui

cot = dados.tabela("b3_cotacoes")
prov = dados.tabela("b3_proventos")
desemp = dados.tabela("b3_desempenho")
selic = dados.tabela("selic_mes")

ui.cabecalho("Simulador de investimento", "Escolha um papel, a data e o valor da compra: o simulador compra ao preço "
             "<b>da época</b>, acompanha desdobramentos, grupamentos e bonificações, soma os dividendos, JCP e "
             "rendimentos recebidos, desconta o IR de uma venda hoje e compara com a Selic e o Ibovespa (BOVA11).")

# ---------------------------------------------------------------- escolhas
CLASSES = {"Ações": "Ação", "FII": "FII", "ETF": "ETF e fundos"}
disponiveis = desemp[desemp["ticker"].isin(cot["ticker"].unique())]
c1, c2, c3, c4 = st.columns([1.2, 2.4, 1.3, 1.3])
classe = CLASSES[c1.segmented_control("Classe", list(CLASSES), default="Ações", key="sim_classe") or "Ações"]
opcoes = disponiveis[disponiveis["classe_ativo"] == classe].sort_values("volume_medio_diario", ascending=False)
nomes = {r.ticker: f"{r.ticker} · {(r.nome_emissor if pd.notna(r.nome_emissor) else r.nome_pregao)[:30]}"
         for r in opcoes.itertuples()}
padrao = {"Ação": "PETR4", "FII": "KNCR11", "ETF e fundos": "BOVA11"}[classe]
lista = list(nomes)
ticker = c2.selectbox("Papel", lista, index=lista.index(padrao) if padrao in lista else 0, format_func=nomes.get,
                      key=f"sim_ticker_{classe}")
precos = cot[cot["ticker"] == ticker].sort_values("data")
inicio, fim = precos["data"].min().date(), precos["data"].max().date()
data_compra = c3.date_input("Data da compra", value=max(inicio, date(2023, 5, 2)), min_value=inicio, max_value=fim,
                            format="DD/MM/YYYY", key="sim_data")
valor = c4.number_input("Valor investido (R$)", min_value=100.0, value=10_000.0, step=1_000.0, format="%.2f",
                        key="sim_valor")
o1, o2, o3, _ = st.columns([1.4, 1.6, 2.2, 1.2])
reinvestir = o1.toggle("Reinvestir proventos", value=False, help="Compra mais ações no pregão seguinte à data com")
ir_jcp = o2.toggle("Descontar IR de 15 % do JCP", value=True,
                   help="O JCP é pago com imposto retido na fonte; dividendos e rendimentos de FII são isentos para "
                        "pessoa física")
isencao = o3.toggle("Isenção de vendas até R$ 20 mil/mês", value=True, disabled=classe != "Ação",
                    help="Só para ações: se o total vendido no mês (todas as ações) for até R$ 20 mil, o lucro é "
                         "isento. Supõe que esta é a única venda do mês. FII (20 %) e ETF (15 %) não têm isenção.")

proventos = prov[prov["ticker"] == ticker][["data_com", "tipo", "valor_por_acao"]]
r = simulador.simular(precos, proventos, valor, pd.Timestamp(data_compra), reinvestir=reinvestir, ir_jcp=ir_jcp)
for aviso in r.avisos:
    ui.aviso(aviso)

# ---------------------------------------------------------------- resultado
bova = simulador.referencia(cot[cot["ticker"] == "BOVA11"], r.investido, r.data_compra)
sel = simulador.selic_acumulada(selic, r.investido, r.data_compra, r.serie["data"])
ret_bova = bova["valor"].iat[-1] / r.investido - 1 if len(bova) and r.investido else float("nan")
ret_selic = sel["valor"].iat[-1] / r.investido - 1 if len(sel) and r.investido else float("nan")
imp = simulador.imposto_venda(classe, r.valor_hoje, r.custo_aquisicao, isencao)
total_liquido = r.total_hoje - imp.imposto
lucro_liquido = total_liquido - r.investido
dias = (r.data_hoje - r.data_compra).days
anual = lambda total: (total / r.investido) ** (365.25 / dias) - 1 if dias > 30 and r.investido else float("nan")  # noqa: E731
selic_liq = simulador.selic_liquida(ret_selic, dias)
pc = lambda v: formato.pct(v * 100, 1, sinal=True)  # noqa: E731
ui.kpis([
    {"rotulo": f"Compra em {formato.data(r.data_compra)}", "valor": formato.brl(r.investido),
     "icone": "carteira", "nota": f"{formato.numero(r.acoes_compradas)} × {formato.brl(r.preco_compra)}"
     + (f" · sobra {formato.brl(r.sobra)}" if r.sobra >= 0.01 else "")},
    {"rotulo": "Valorização (preço)", "valor": formato.brl(r.valorizacao), "icone": "subida",
     "nota": f"{pc(r.valorizacao / r.investido) if r.investido else '—'} · hoje {formato.numero(r.acoes_hoje, 2)} "
             f"× {formato.brl(r.preco_hoje)}", "tom": "pos" if r.valorizacao >= 0 else "neg"},
    {"rotulo": "Proventos recebidos", "valor": formato.brl(r.proventos_recebidos), "icone": "fluxo",
     "nota": (f"{pc(r.proventos_recebidos / r.investido) if r.investido else '—'} do investido · "
              + ("reinvestidos" if reinvestir else "em dinheiro"))},
    {"rotulo": f"Total líquido em {formato.data(r.data_hoje)}", "valor": formato.brl(total_liquido), "icone": "check",
     "nota": f"depois do IR · {pc(lucro_liquido / r.investido)} ({pc(anual(total_liquido))} ao ano)",
     "tom": "pos" if lucro_liquido >= 0 else "neg"},
])

with ui.card("sim_resumo"):
    ui.titulo_card("Resumo da simulação", f"Se vendesse tudo em {formato.data(r.data_hoje)} ao fecho de "
                   f"{formato.brl(r.preco_hoje)}")
    ir_jcp_total = float(r.proventos["ir"].sum()) if len(r.proventos) else 0.0
    linhas = [
        ("Valor investido", f"{formato.numero(r.acoes_compradas)} × {formato.brl(r.preco_compra)} em "
                            f"{formato.data(r.data_compra)}", r.investido),
        ("Valor das ações hoje", f"{formato.numero(r.acoes_hoje, 2)} × {formato.brl(r.preco_hoje)}", r.valor_hoje),
        ("Proventos recebidos", "líquidos" + (f" (IR do JCP retido: {formato.brl(ir_jcp_total)})" if ir_jcp_total else "")
         + (" · reinvestidos em ações" if reinvestir else ""), r.proventos_recebidos),
        ("Total bruto", "ações hoje + proventos em dinheiro", r.total_hoje),
        ("Lucro antes do IR", "total bruto − investido", r.total_hoje - r.investido),
        ("IR sobre o lucro da venda", f"{imp.motivo} · base {formato.brl(imp.lucro)} (venda − custo "
                                      f"{formato.brl(imp.custo)})", -imp.imposto),
        ("Total líquido", "o que ficaria depois de vender e pagar o IR", total_liquido),
        ("Lucro líquido", f"{pc(lucro_liquido / r.investido)} no período · {pc(anual(total_liquido))} ao ano",
         lucro_liquido),
    ]
    tabela = pd.DataFrame(linhas, columns=["Item", "Como", "valor"])
    tabela["Valor"] = tabela["valor"].map(formato.brl)
    tabela["% do investido"] = [formato.pct(v / r.investido * 100, 1) if r.investido else "—" for v in tabela["valor"]]
    st.dataframe(tabela[["Item", "Como", "Valor", "% do investido"]], hide_index=True, width="stretch",
                 column_config={"Item": st.column_config.TextColumn(width="medium"),
                                "Como": st.column_config.TextColumn(width="large"),
                                "Valor": st.column_config.TextColumn(),
                                "% do investido": st.column_config.TextColumn()})
    ui.aviso(f"Comparação no mesmo período: <b>Selic</b> {pc(ret_selic)} bruto, {pc(selic_liq)} líquido de IR "
             f"(tabela regressiva, {simulador.aliquota_renda_fixa(dias) * 100:.1f} %) · <b>Ibovespa (BOVA11)</b> "
             f"{pc(ret_bova)} antes de IR. Não inclui corretagem nem compensação de prejuízos anteriores.")

g1, g2 = st.columns([3, 2], gap="medium")
with g1, ui.card("sim_evolucao"):
    ui.titulo_card("Evolução do património", "Valor das ações + proventos recebidos, comparado com o mesmo valor na "
                   "Selic e no BOVA11 (R$)")
    series = pd.concat([
        r.serie[["data", "patrimonio"]].rename(columns={"patrimonio": "valor"}).assign(serie=f"{ticker} (ações + proventos)"),
        r.serie[["data", "valor_posicao"]].rename(columns={"valor_posicao": "valor"}).assign(serie=f"{ticker} (só ações)"),
        sel.assign(serie="Selic"),
        bova.assign(serie="BOVA11 (Ibovespa)"),
    ])
    graficos.mostrar(graficos.linhas(series, "data", "valor", "serie", "", 0, altura=340))
with g2, ui.card("sim_composicao"):
    ui.titulo_card("De onde vem o resultado", "Decomposição do ganho ou perda total")
    decomp = pd.DataFrame({"componente": ["Valorização", "Proventos", "Total"],
                           "valor": [r.valorizacao, r.proventos_recebidos, r.total_hoje - r.investido]})
    graficos.mostrar(graficos.barras_sinal(decomp, "componente", "valor", "", 2, altura=250))
    st.caption("Valorização = total de hoje − investido − proventos. Com reinvestimento, a variação de preço das ações "
               "compradas com proventos entra na valorização. IR sobre ganho de capital não é descontado.")

e1, e2 = st.columns([2, 3], gap="medium")
with e1, ui.card("sim_eventos"):
    ui.titulo_card("Eventos nas ações", "Desdobramentos, grupamentos e bonificações desde a compra")
    if r.eventos.empty:
        st.caption("Nenhum evento desde a compra: a quantidade não mudou.")
    else:
        st.dataframe(r.eventos[["data", "descricao", "acoes_antes", "acoes_depois"]], hide_index=True, width="stretch",
                     column_config={"data": st.column_config.DateColumn("Data ex", format="DD/MM/YYYY"),
                                    "descricao": st.column_config.TextColumn("Evento"),
                                    "acoes_antes": st.column_config.NumberColumn("Antes", format="%.2f"),
                                    "acoes_depois": st.column_config.NumberColumn("Depois", format="%.2f")})
        st.caption("Frações de ações resultantes de bonificações são, na prática, vendidas pela B3 e pagas em dinheiro.")
with e2, ui.card("sim_proventos"):
    ui.titulo_card("Proventos recebidos", f"{len(r.proventos)} pagamentos · posição no fim de cada data com")
    if r.proventos.empty:
        st.caption("Sem proventos desde a compra" + (" (FII sem rendimentos informados à CVM?)" if classe == "FII" else "."))
    else:
        anual = r.proventos.assign(ano=r.proventos["data_com"].dt.year.astype(str)).groupby("ano", as_index=False)["liquido"].sum()
        graficos.mostrar(graficos.barras(anual, "ano", "liquido", "R$", 2, altura=200))
        st.dataframe(r.proventos.sort_values("data_com", ascending=False), hide_index=True, width="stretch", height=260,
                     column_config={"data_com": st.column_config.DateColumn("Data com", format="DD/MM/YYYY"),
                                    "tipo": st.column_config.TextColumn("Tipo"),
                                    "valor_por_acao": st.column_config.NumberColumn("R$/ação", format="%.4f"),
                                    "acoes": st.column_config.NumberColumn("Ações", format="%.2f"),
                                    "bruto": st.column_config.NumberColumn("Bruto (R$)", format="%.2f"),
                                    "ir": st.column_config.NumberColumn("IR (R$)", format="%.2f"),
                                    "liquido": st.column_config.NumberColumn("Líquido (R$)", format="%.2f"),
                                    "reinvestido_a": st.column_config.NumberColumn("Reinvestido a", format="%.2f")})

ui.rodape("Simulação com dados da B3 (preços de fecho do COTAHIST desde 2021; dividendos e JCP e eventos oficiais das "
          "empresas listadas) e da CVM (rendimentos de FII = DY do mês × cota patrimonial do informe mensal, "
          "conferidos com a B3). IR da venda: 15 % ações e ETF, 20 % FII, isenção de R$ 20 mil/mês só em ações; bonificações "
          "entram com custo zero. Não inclui corretagem nem emolumentos. Papéis com volume "
          "médio ≥ R$ 300 mil/dia. Projeto de estudo, não é recomendação.")
