"""Modelo preditivo (experimental): ranking de ações para o mês seguinte, com o backtest walk-forward."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from painel import dados, formato, graficos, modelo_vivo, ui

resumo = dados.tabela("ml_resumo").set_index("modelo")
bt = dados.tabela("ml_backtest")
bt["data_ref"] = pd.to_datetime(bt["data_ref"])
imp = dados.tabela("ml_importancia")
rk = dados.tabela("ml_ranking").sort_values("posicao")
NOMES = {"gbm": "Gradient boosting", "logistica": "Regressão logística", "momentum": "Momentum 12-1 (sem ML)"}
NOMES_VAR = {
    "r_ret_1m": "Retorno 1 mês", "r_ret_3m": "Retorno 3 meses", "r_ret_6m": "Retorno 6 meses",
    "r_mom_12_1": "Momentum 12-1", "r_vol_3m": "Volatilidade 3 meses", "r_log_volume": "Volume negociado",
    "r_dist_max_52s": "Distância à máxima de 52 sem.", "r_dy_12m": "Dividend yield 12m",
    "r_earnings_yield": "Lucro / valor de mercado", "r_book_to_market": "PL / valor de mercado", "r_roe": "ROE",
    "r_margem_liquida": "Margem líquida", "r_divida_liquida_pl": "Dívida líquida / PL",
    "r_log_valor_mercado": "Valor de mercado", "selic_meta": "Selic (meta)", "selic_var_3m": "Variação da Selic 3m",
    "usd_ret_1m": "Dólar 1 mês", "setor_cod": "Setor"}

ui.cabecalho("Modelo (experimental)", "Pergunta: <b>esta ação vai render mais do que a mediana das ações líquidas nos "
             "próximos 21 pregões?</b> Validado mês a mês sem olhar para o futuro (walk-forward). Projeto de estudo: "
             "<b>não é recomendação de investimento</b>.",
             selo=f"Ranking de {formato.data(pd.Timestamp(rk['data_ref'].iloc[0]))}" if len(rk) else None)

g = resumo.loc["gbm"] if "gbm" in resumo.index else resumo.iloc[0]
ui.kpis([
    {"rotulo": "AUC média fora da amostra", "valor": formato.numero(g["auc_media"], 3), "icone": "check",
     "nota": "0,5 = acaso; acima de 0,55 já é raro em ações"},
    {"rotulo": "IC médio (Spearman)", "valor": formato.numero(g["ic_medio"], 3), "icone": "atividade",
     "nota": f"t = {formato.numero(g['ic_t'], 2)} · positivo em {formato.pct(g['ic_positivo_pct'] * 100, 0)} dos meses",
     "tom": "pos" if g["ic_medio"] > 0 else "neg"},
    {"rotulo": "Carteira top 10 (acumulado)", "valor": formato.pct(g["ret_carteira_acum"] * 100, 1, sinal=True),
     "icone": "subida", "nota": f"universo {formato.pct(g['ret_universo_acum'] * 100, 1, sinal=True)} · BOVA11 "
     f"{formato.pct(g.get('ret_referencia_acum', float('nan')) * 100, 1, sinal=True)}",
     "tom": "pos" if g["ret_carteira_acum"] > g["ret_universo_acum"] else "neg"},
    {"rotulo": "Meses avaliados", "valor": formato.numero(g["meses"]), "icone": "calendario",
     "nota": f"de {formato.mes(bt['data_ref'].min())} a {formato.mes(bt['data_ref'].max())}"},
])

with ui.card("ml_vivo"):
    ui.titulo_card("Acompanhamento ao vivo", "Cada ranking fica gravado quando é publicado e nunca é alterado; o "
                   "resultado é medido nos 21 pregões seguintes, com preços que ainda não existiam. Retornos brutos, "
                   "carteira das 10 primeiras posições com igual peso")
    acomp = (dados.tabela("ml_acompanhamento") if "ml_acompanhamento" in dados.meta().get("linhas", {})
             else pd.DataFrame())
    if len(acomp):
        for col in ("data_ref", "data_fim"):
            acomp[col] = pd.to_datetime(acomp[col])
        acomp["publicado_em"] = pd.to_datetime(acomp["publicado_em"], utc=True)
    viv = modelo_vivo.resumir(acomp)
    pl = modelo_vivo.placar(viv)
    if viv.empty:
        st.caption("Ainda não há rankings gravados: o primeiro entra na próxima execução semanal do modelo.")
    else:
        pc = lambda v: formato.pct(v * 100, 1, sinal=True) if pd.notna(v) else "—"  # noqa: E731
        if pl["concluidos"]:
            ui.kpis([
                {"rotulo": "Rankings concluídos", "valor": formato.numero(pl["concluidos"]), "icone": "calendario",
                 "nota": f"{pl['em_curso']} em curso"},
                {"rotulo": "Top 10 − universo (média)", "valor": pc(pl["excesso_medio"]), "icone": "subida",
                 "nota": f"top 10 acima do universo em {formato.pct(pl['venceu_universo'] * 100, 0)} dos rankings",
                 "tom": "pos" if pl["excesso_medio"] > 0 else "neg"},
                {"rotulo": "IC médio ao vivo", "valor": formato.numero(pl["ic_medio"], 3), "icone": "atividade",
                 "nota": f"backtest: {formato.numero(g['ic_medio'], 3)}", "tom": "pos" if pl["ic_medio"] > 0 else "neg"},
                {"rotulo": "Acerto do top 10", "valor": formato.pct(pl["acerto_medio"] * 100, 0), "icone": "check",
                 "nota": "ações do top 10 acima da mediana (50 % = acaso)"},
            ])
        else:
            primeiro = viv["data_ref"].min()
            previsto = primeiro + pd.Timedelta(days=30)
            ui.aviso(f"Primeiro ranking gravado: <b>{formato.data(primeiro)}</b>. O resultado vai aparecendo a cada "
                     f"pregão e fica completo (21 pregões) por volta de <b>{formato.data(previsto)}</b>. Até haver "
                     "vários rankings concluídos, o resultado diz pouco: um mês pode ser sorte.")
        t = viv.copy()
        t["estado"] = [("concluído" if c_ else f"em curso ({p_}/{modelo_vivo.HORIZONTE})")
                       for c_, p_ in zip(t["concluido"], t["pregoes"])]
        for c_ in ("ret_top", "ret_universo", "ret_bova11", "excesso", "acerto"):
            t[c_] = t[c_] * 100
        st.dataframe(t[["data_ref", "estado", "ret_top", "ret_universo", "ret_bova11", "excesso", "acerto", "ic",
                        "modelo"]], hide_index=True, width="stretch",
                     column_config={
                         "data_ref": st.column_config.DateColumn("Ranking de", format="DD/MM/YYYY"),
                         "estado": st.column_config.TextColumn("Estado"),
                         "ret_top": st.column_config.NumberColumn("Top 10 (%)", format="%+.2f"),
                         "ret_universo": st.column_config.NumberColumn("Universo (%)", format="%+.2f"),
                         "ret_bova11": st.column_config.NumberColumn("BOVA11 (%)", format="%+.2f"),
                         "excesso": st.column_config.NumberColumn("Top 10 − universo (p.p.)", format="%+.2f"),
                         "acerto": st.column_config.NumberColumn("Acerto (%)", format="%.0f"),
                         "ic": st.column_config.NumberColumn("IC", format="%+.3f"),
                         "modelo": st.column_config.TextColumn("Modelo")})
        datas_rk = list(viv["data_ref"])
        escolha = st.selectbox("Ver as ações de um ranking", datas_rk, format_func=formato.data, key="ml_vivo_data")
        sel = acomp[(acomp["data_ref"] == escolha) & acomp["posicao"].notna()].sort_values("posicao")
        st.dataframe(sel[["posicao", "ticker", "setor", "score", "pregoes", "ret"]].assign(
                         score=lambda x: x["score"] * 100, ret=lambda x: x["ret"] * 100),
                     hide_index=True, width="stretch", height=300,
                     column_config={"posicao": st.column_config.NumberColumn("#", width="small"),
                                    "ticker": "Ticker", "setor": "Setor",
                                    "score": st.column_config.NumberColumn("Probabilidade (%)", format="%.1f"),
                                    "pregoes": st.column_config.NumberColumn("Pregões"),
                                    "ret": st.column_config.NumberColumn("Retorno até agora (%)", format="%+.2f")})

c1, c2 = st.columns([3, 2], gap="medium")
with c1, ui.card("ml_acumulado"):
    ui.titulo_card("Backtest: carteira das 10 maiores pontuações", "Retorno acumulado com custos de transação "
                   "(0,10 % por lado); rebalanceamento mensal; igual peso")
    modelo = st.segmented_control("Modelo", list(NOMES), default="gbm", format_func=NOMES.get, key="ml_modelo",
                                  label_visibility="collapsed") or "gbm"
    m = bt[bt["modelo"] == modelo].sort_values("data_ref")
    series = pd.concat([
        pd.DataFrame({"data": m["data_ref"], "valor": (1 + m["ret_carteira"]).cumprod() * 100, "serie": "Carteira top 10"}),
        pd.DataFrame({"data": m["data_ref"], "valor": (1 + m["ret_universo"]).cumprod() * 100, "serie": "Universo (média)"}),
        pd.DataFrame({"data": m["data_ref"], "valor": (1 + m["ret_bova11"].fillna(0)).cumprod() * 100, "serie": "BOVA11"}),
    ])
    graficos.mostrar(graficos.linhas(series, "data", "valor", "serie", "", 1, altura=320))
with c2, ui.card("ml_modelos"):
    ui.titulo_card("Comparação dos modelos", "Mesmo período, mesmas regras")
    t = resumo.reset_index()[["modelo", "auc_media", "ic_medio", "ret_carteira_acum", "max_drawdown"]]
    t["modelo"] = t["modelo"].map(NOMES)
    for c in ("ret_carteira_acum", "max_drawdown"):
        t[c] = t[c] * 100
    st.dataframe(t, hide_index=True, width="stretch", column_config={
        "modelo": st.column_config.TextColumn("Modelo"),
        "auc_media": st.column_config.NumberColumn("AUC", format="%.3f"),
        "ic_medio": st.column_config.NumberColumn("IC", format="%+.3f"),
        "ret_carteira_acum": st.column_config.NumberColumn("Carteira (%)", format="%+.1f"),
        "max_drawdown": st.column_config.NumberColumn("Queda máx. (%)", format="%.1f")})
    ui.aviso("Um IC médio perto de zero ou um <i>t</i> abaixo de 2 querem dizer que a diferença pode ser sorte. "
             "Resultados passados, mesmo fora da amostra, não garantem resultados futuros.")

c3, c4 = st.columns(2, gap="medium")
with c3, ui.card("ml_ic"):
    ui.titulo_card("IC por mês", "Correlação entre a pontuação e o retorno realizado das ações nesse mês")
    graficos.mostrar(graficos.barras_sinal(m.assign(mes=m["data_ref"]), "mes", "ic", "", 3, altura=280))
with c4, ui.card("ml_importancia"):
    ui.titulo_card("O que pesa no modelo", "Queda da AUC ao baralhar cada variável (permutação), últimos 12 meses "
                   "fora da amostra")
    i = imp.assign(nome=imp["variavel"].map(NOMES_VAR).fillna(imp["variavel"]), valor=imp["importancia"] * 100)
    graficos.mostrar(graficos.barras_h(i.nlargest(10, "valor"), "nome", "valor", "", 2, altura=300))

with ui.card("ml_ranking"):
    ui.titulo_card("Ranking atual (gradient boosting)", "Probabilidade estimada de render acima da mediana nos próximos "
                   "21 pregões · as variáveis mostram porque a ação está onde está")
    r = rk.copy()
    r["p_l"] = (1 / r["earnings_yield"]).where(r["earnings_yield"] > 0)
    r["p_vp"] = (1 / r["book_to_market"]).where(r["book_to_market"] > 0)
    for c in ("score", "mom_12_1", "ret_1m", "dy_12m", "roe", "vol_3m"):
        r[c] = r[c] * 100
    st.dataframe(
        r[["posicao", "ticker", "setor", "score", "mom_12_1", "ret_1m", "vol_3m", "dy_12m", "p_l", "p_vp", "roe"]],
        hide_index=True, width="stretch", height=460,
        column_config={
            "posicao": st.column_config.NumberColumn("#", width="small"),
            "ticker": st.column_config.TextColumn("Ticker", pinned=True),
            "setor": st.column_config.TextColumn("Setor", width="medium"),
            "score": st.column_config.ProgressColumn("Probabilidade (%)", format="%.1f", min_value=0, max_value=100),
            "mom_12_1": st.column_config.NumberColumn("Momentum 12-1 (%)", format="%+.1f"),
            "ret_1m": st.column_config.NumberColumn("1 mês (%)", format="%+.1f"),
            "vol_3m": st.column_config.NumberColumn("Volatilidade (%)", format="%.0f"),
            "dy_12m": st.column_config.NumberColumn("DY 12m (%)", format="%.1f"),
            "p_l": st.column_config.NumberColumn("P/L", format="%.1f"),
            "p_vp": st.column_config.NumberColumn("P/VP", format="%.2f"),
            "roe": st.column_config.NumberColumn("ROE (%)", format="%.1f")})

with st.expander("Como o modelo funciona"):
    st.markdown(
        "- **Universo:** ações em lote padrão com volume médio ≥ R$ 1 mi/dia e pelo menos 1 ano de histórico.\n"
        "- **Variáveis** (em percentil entre as ações do mesmo mês): retornos de 1, 3 e 6 meses, momentum 12-1, "
        "volatilidade, volume, distância à máxima de 52 semanas, dividend yield, lucro e PL sobre valor de mercado, "
        "ROE, margem, dívida líquida/PL, tamanho; mais Selic, variação da Selic e dólar, e o setor.\n"
        "- **Sem olhar para o futuro:** fundamentos só a partir da data de entrega à CVM; dividendos só depois da data "
        "ex; o treino de cada mês só usa meses cujo resultado já era conhecido, com um mês de intervalo.\n"
        "- **Alvo:** retorno total (preço + dividendos) nos 21 pregões seguintes acima da mediana.\n"
        "- **Limitações:** só ~5 anos de dados (um ciclo de juros); o valor de mercado usa o preço de uma das classes; "
        "empresas que deixaram de ser negociadas antes de 2021 não entram (enviesamento de sobrevivência parcial); "
        "custos reais variam com a corretora e a liquidez.")

ui.rodape("Modelo treinado no Databricks (scikit-learn, registado no MLflow / Unity Catalog) com dados da B3 "
          "(cotações e proventos), CVM (DFP/ITR) e Banco Central (Selic, PTAX).")
