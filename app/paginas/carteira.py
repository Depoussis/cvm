"""Simulador de carteira: vários papéis com pesos, aporte inicial e aportes mensais, retorno real e comparações."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from painel import carteira, dados, formato, graficos, simulador, ui

cot = dados.tabela("b3_cotacoes")
prov = dados.tabela("b3_proventos")
desemp = dados.tabela("b3_desempenho")
indices = dados.tabela("indices_mes") if "indices_mes" in dados.meta().get("linhas", {}) else pd.DataFrame(
    columns=["mes", "selic", "cdi", "ipca"])

ui.cabecalho("Carteira com aportes", "Monte uma carteira com vários papéis e pesos, defina o aporte inicial e um "
             "aporte mensal: cada aporte compra os papéis ao preço <b>da época</b>. Veja o total líquido de IR, o "
             "ganho <b>acima da inflação</b> e a comparação com o CDI e o Ibovespa com os mesmos aportes.")

# ---------------------------------------------------------------- escolhas
CLASSE_ROTULO = {"Ação": "Ação", "FII": "FII", "ETF e fundos": "ETF"}
disp = desemp[desemp["ticker"].isin(cot["ticker"].unique())].sort_values("volume_medio_diario", ascending=False)
classes = dict(zip(disp["ticker"], disp["classe_ativo"]))
nomes = {r.ticker: (r.nome_emissor if pd.notna(r.nome_emissor) else r.nome_pregao) for r in disp.itertuples()}
inicio_dados, fim_dados = cot["data"].min().date(), cot["data"].max().date()

c1, c2, c3 = st.columns(3)
data_inicio = c1.date_input("Primeiro aporte", value=max(inicio_dados, date(2023, 5, 2)), min_value=inicio_dados,
                            max_value=fim_dados, format="DD/MM/YYYY", key="cart_data")
valor_inicial = c2.number_input("Aporte inicial (R$)", min_value=0.0, value=10_000.0, step=1_000.0, format="%.2f",
                                key="cart_inicial")
aporte_mensal = c3.number_input("Aporte mensal (R$)", min_value=0.0, value=1_000.0, step=100.0, format="%.2f",
                                key="cart_mensal", help="Investido no mesmo dia de cada mês, dividido pelos pesos")

PADRAO = pd.DataFrame({"Papel": ["PETR4", "ITUB4", "WEGE3", "KNCR11", "BOVA11"], "Peso (%)": [20.0, 20, 20, 20, 20]})
st.caption("Carteira: escolha os papéis e os pesos (pode acrescentar ou apagar linhas). Os pesos são normalizados "
           "para somar 100 %.")
editada = st.data_editor(
    PADRAO[PADRAO["Papel"].isin(classes)], num_rows="dynamic", hide_index=True, width="stretch", key="cart_papeis",
    column_config={"Papel": st.column_config.SelectboxColumn(options=list(classes), required=True, width="medium"),
                   "Peso (%)": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=5.0,
                                                             format="%.0f", required=True)})
o1, o2, o3 = st.columns([1.4, 1.6, 2.2])
reinvestir = o1.toggle("Reinvestir proventos", value=False, key="cart_reinv")
ir_jcp = o2.toggle("Descontar IR de 15 % do JCP", value=True, key="cart_jcp")
isencao = o3.toggle("Isenção de vendas de ações até R$ 20 mil/mês", value=True, key="cart_isencao")

pesos = (editada.dropna().groupby("Papel")["Peso (%)"].sum())
pesos = pesos[pesos > 0]
if pesos.empty:
    ui.aviso("Escolha pelo menos um papel com peso maior que zero.")
    st.stop()
if valor_inicial <= 0 and aporte_mensal <= 0:
    ui.aviso("Defina um aporte inicial ou um aporte mensal.")
    st.stop()


@st.cache_data(show_spinner="A simular a carteira…", max_entries=20)
def _simular(pesos: tuple, inicio: date, inicial: float, mensal: float, reinv: bool, jcp: bool, isen: bool,
             versao: str) -> carteira.Carteira:
    tickers = [t for t, _ in pesos]
    precos = {t: cot[cot["ticker"] == t].sort_values("data") for t in tickers}
    provs = {t: prov[prov["ticker"] == t][["data_com", "tipo", "valor_por_acao"]] for t in tickers}
    return carteira.simular_carteira(precos, provs, {t: classes[t] for t in tickers}, dict(pesos), inicial, mensal,
                                     pd.Timestamp(inicio), reinvestir=reinv, ir_jcp=jcp, isencao=isen)


c = _simular(tuple(sorted(pesos.items())), data_inicio, valor_inicial, aporte_mensal, reinvestir, ir_jcp, isencao,
             dados.meta().get("exportado_em", ""))
for aviso in c.avisos:
    ui.aviso(aviso)

# ---------------------------------------------------------------- resultado
pc = lambda v: formato.pct(v * 100, 1, sinal=True) if pd.notna(v) else "—"  # noqa: E731
aportado = c.total_aportado
lucro = c.total_liquido - aportado
taxa = carteira.tir(c.aportes, c.total_liquido, c.data_hoje)
tem_ipca = indices["ipca"].notna().any() if len(indices) else False
tem_cdi = indices["cdi"].notna().any() if len(indices) else False
ipca = carteira.indice_mensal(indices, "ipca") if tem_ipca else None
corrigido = carteira.corrigido_ipca(c.aportes, ipca, c.data_hoje) if tem_ipca else float("nan")
ganho_real = c.total_liquido - corrigido
proventos = float(c.posicoes["proventos"].sum())
n = len(c.aportes)

ui.kpis([
    {"rotulo": "Total aportado", "valor": formato.brl(aportado), "icone": "carteira",
     "nota": f"{n} aporte{'s' if n > 1 else ''} de {formato.data(c.data_inicio)} a "
             f"{formato.data(c.aportes['data'].iat[-1])}"},
    {"rotulo": f"Total líquido em {formato.data(c.data_hoje)}", "valor": formato.brl(c.total_liquido),
     "icone": "check", "nota": f"lucro {formato.brl(lucro)} · TIR {pc(taxa)} ao ano",
     "tom": "pos" if lucro >= 0 else "neg"},
    {"rotulo": "Ganho acima da inflação", "valor": formato.brl(ganho_real) if tem_ipca else "—", "icone": "subida",
     "nota": (f"aportes corrigidos pelo IPCA: {formato.brl(corrigido)}" if tem_ipca else "IPCA ainda não exportado"),
     "tom": "pos" if tem_ipca and ganho_real >= 0 else "neg"},
    {"rotulo": "Proventos recebidos", "valor": formato.brl(proventos), "icone": "fluxo",
     "nota": f"{pc(proventos / aportado)} do aportado · " + ("reinvestidos" if reinvestir else "em dinheiro")},
])

# comparações com os mesmos aportes
datas = c.serie["data"]
bova = cot[cot["ticker"] == "BOVA11"].set_index("data")["preco_ajustado"]
bova_serie = carteira.aplicar_fluxos(c.aportes, datas, bova, mensal=False) if len(bova) else None
comp = []
if tem_cdi:
    cdi = carteira.indice_mensal(indices, "cdi")
    cdi_bruto, cdi_liq = carteira.renda_fixa_liquida(c.aportes, cdi, c.data_hoje)
    comp.append(("CDI (mesmos aportes)", "líquido de IR pela tabela regressiva de cada aporte", cdi_liq))
    selic_idx = carteira.indice_mensal(indices, "selic")
    comp.append(("Selic / Tesouro Selic", "líquido de IR, sem custódia",
                 carteira.renda_fixa_liquida(c.aportes, selic_idx, c.data_hoje)[1]))
if bova_serie is not None and len(bova_serie):
    bova_final = float(bova_serie["valor"].iat[-1])
    imp_bova = simulador.imposto_venda("ETF e fundos", bova_final, aportado)
    comp.append(("Ibovespa (BOVA11, mesmos aportes)", "líquido do IR de 15 % na venda", bova_final - imp_bova.imposto))
if tem_ipca:
    comp.append(("Só a inflação (IPCA)", "o que manteria o poder de compra dos aportes", corrigido))

with ui.card("cart_resumo"):
    ui.titulo_card("Resumo", f"Se vendesse tudo em {formato.data(c.data_hoje)}")
    linhas = [("Total aportado", f"{n} aportes", aportado),
              ("Valor dos papéis hoje", "quantidade × fecho de hoje", float(c.posicoes["valor_hoje"].sum())),
              ("Proventos em dinheiro", "líquidos de IR do JCP" + (" (reinvestidos: já estão nos papéis)"
                                                                   if reinvestir else ""),
               float(c.posicoes["proventos_em_caixa"].sum())),
              ("Caixa não investido", "sobras por não comprar frações", float(c.posicoes["caixa"].sum())),
              ("Total bruto", "papéis + proventos + caixa", c.total_bruto)]
    for classe, imp in c.impostos.items():
        linhas.append((f"IR na venda · {CLASSE_ROTULO.get(classe, classe)}",
                       f"{imp.motivo} · lucro {formato.brl(imp.lucro)}", -imp.imposto))
    linhas += [("Total líquido", "depois de vender e pagar o IR", c.total_liquido),
               ("Lucro líquido", f"TIR {pc(taxa)} ao ano (rentabilidade ponderada pelos aportes)", lucro)]
    if tem_ipca:
        linhas.append(("Ganho real", "total líquido − aportes corrigidos pelo IPCA", ganho_real))
    tabela = pd.DataFrame(linhas, columns=["Item", "Como", "valor"])
    tabela["Valor"] = tabela["valor"].map(formato.brl)
    st.dataframe(tabela[["Item", "Como", "Valor"]], hide_index=True, width="stretch",
                 column_config={"Item": st.column_config.TextColumn(width="medium"),
                                "Como": st.column_config.TextColumn(width="large")})

g1, g2 = st.columns([3, 2], gap="medium")
with g1, ui.card("cart_evolucao"):
    ui.titulo_card("Evolução do património", "Carteira (papéis + proventos) contra o total aportado e os mesmos "
                   "aportes no CDI e no BOVA11 (R$, antes de IR)")
    partes = [c.serie[["data", "patrimonio"]].rename(columns={"patrimonio": "valor"}).assign(serie="Carteira"),
              c.serie[["data", "aportado"]].rename(columns={"aportado": "valor"}).assign(serie="Total aportado")]
    if tem_cdi:
        partes.append(carteira.aplicar_fluxos(c.aportes, datas, cdi, mensal=True).assign(serie="CDI"))
    if bova_serie is not None:
        partes.append(bova_serie.assign(serie="BOVA11 (Ibovespa)"))
    graficos.mostrar(graficos.linhas(pd.concat(partes), "data", "valor", "serie", "", 0, altura=340))
with g2, ui.card("cart_comparacao"):
    ui.titulo_card("Comparação no fim", "Total líquido de cada alternativa com os mesmos aportes")
    comp_df = pd.DataFrame([("Esta carteira", "", c.total_liquido)] + comp, columns=["alternativa", "como", "valor"])
    comp_df["vs aportado"] = [pc(v / aportado - 1) for v in comp_df["valor"]]
    comp_df["Valor"] = comp_df["valor"].map(formato.brl)
    st.dataframe(comp_df[["alternativa", "Valor", "vs aportado", "como"]], hide_index=True, width="stretch",
                 column_config={"alternativa": st.column_config.TextColumn("Alternativa", width="medium"),
                                "como": st.column_config.TextColumn("Como")})

with ui.card("cart_posicoes"):
    ui.titulo_card("Posições por papel", "Quanto foi para cada papel e quanto vale hoje")
    p = c.posicoes.assign(nome=lambda x: x["ticker"].map(nomes), classe=lambda x: x["classe"].map(CLASSE_ROTULO),
                          resultado=lambda x: x["valor_hoje"] + x["proventos_em_caixa"] + x["caixa"] - x["aportado"])
    p["retorno"] = p["resultado"] / p["aportado"] * 100
    st.dataframe(p[["ticker", "nome", "classe", "peso", "aportado", "acoes", "preco", "valor_hoje", "proventos",
                    "resultado", "retorno"]], hide_index=True, width="stretch",
                 column_config={"ticker": "Papel", "nome": "Nome", "classe": "Classe",
                                "peso": st.column_config.NumberColumn("Peso", format="percent"),
                                "aportado": st.column_config.NumberColumn("Aportado (R$)", format="%.2f"),
                                "acoes": st.column_config.NumberColumn("Quantidade", format="%.2f"),
                                "preco": st.column_config.NumberColumn("Fecho (R$)", format="%.2f"),
                                "valor_hoje": st.column_config.NumberColumn("Valor hoje (R$)", format="%.2f"),
                                "proventos": st.column_config.NumberColumn("Proventos (R$)", format="%.2f"),
                                "resultado": st.column_config.NumberColumn("Resultado (R$)", format="%.2f"),
                                "retorno": st.column_config.NumberColumn("Retorno (%)", format="%.1f")})

ui.rodape("Mesmas regras do simulador de um papel (preços da época, eventos oficiais, proventos na data com, IR da "
          "venda por classe com compensação dentro do mês). Selic, CDI e IPCA: Banco Central (SGS 4390, 4391, 433). "
          "Ganho real compara com os aportes corrigidos pelo IPCA até ao último mês divulgado. Não inclui corretagem "
          "nem emolumentos. Projeto de estudo, não é recomendação.")
