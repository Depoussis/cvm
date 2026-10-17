"""Validação semanal da gold contra fontes externas (scripts/validar_fontes.py, docs/validacao_dados.md)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from painel import formato, ui
from painel import dados

DOC = "https://github.com/Depoussis/cvm/blob/main/docs/validacao_dados.md"
ui.cabecalho("Validação externa", "Todas as semanas a camada gold é comparada, linha a linha, com fontes externas: IBGE, "
             "decisões do Copom, Yahoo Finance e os ficheiros originais da B3, da CVM e do Tesouro. Quando a plataforma e a "
             "fonte discordam, uma terceira referência oficial desempata. "
             f'<a href="{DOC}" target="_blank">Método, imagens das consultas e explicação de cada diferença</a>.')

v = dados.validacao()
if not v.get("verificacoes"):
    ui.aviso("Este snapshot ainda não tem resultados da validação (a primeira validação semanal corre ao domingo).")
    st.stop()

# o que mostra cada verificação e porque é que 100 % nem sempre é o esperado
LEITURA = {
    "ptax": "Mesma fonte (API Olinda do BCB), descarregada de novo: tem de ser 100 %.",
    "selic": "Página do Copom contra a série SGS 432: as duas publicações do BCB só divergem em feriados.",
    "ipca": "IBGE, fonte independente do Banco Central: tem de ser 100 %.",
    "indices": "Yahoo tem fechos errados (sobretudo 2019–2020); a variação do ETF BOVA11 desempata.",
    "cotacoes": "Fecho do último ano ao cêntimo; nos dias diferentes, o ficheiro oficial da B3 (COTAHIST_D) desempata.",
    "eventos": "Desdobramentos, grupamentos e bonificações das 100 ações mais negociadas. Um evento só no Yahoo com o "
               "fecho da B3 compatível é uma bonificação em falta (alerta).",
    "proventos": "Ações: iguais salvo convenções do Yahoo (RENT3, BBDC4). FII: a plataforma estima pelo informe da CVM, "
                 "só se espera proximidade.",
    "fundos": "Todas as linhas do último mês contra o ficheiro da CVM; as diferenças são correções entregues depois da "
              "carga, que a carga seguinte apanha.",
    "tesouro": "Todas as linhas desde 2002 contra o CSV original: tem de ser 100 %.",
}
ORDEM = ["ptax", "selic", "ipca", "indices", "cotacoes", "eventos", "proventos", "fundos", "tesouro"]
verif = {n: v["verificacoes"][n] for n in ORDEM if n in v["verificacoes"]}
alertas = v.get("alertas", [])


def pct(r: dict) -> float:
    return 100 * r["iguais"] / max(r["comparados"], 1)


ok = [r for r in verif.values() if "erro" not in r]
quando = v.get("avaliado_em") or max((r.get("verificado_em", "") for r in ok), default="")
ui.kpis([
    {"rotulo": "Verificações", "valor": str(len(verif)), "icone": "check",
     "nota": f"{sum(1 for r in ok if r.get('independente'))} contra fontes independentes"},
    {"rotulo": "Linhas comparadas", "valor": formato.numero(sum(r["comparados"] for r in ok)), "icone": "camadas",
     "nota": "na última validação"},
    {"rotulo": "Alertas", "valor": str(len(alertas)), "icone": "atividade", "tom": "neg" if alertas else "pos",
     "nota": "limites de config/validacao.yaml" if not alertas else alertas[0][:60]},
    {"rotulo": "Última validação", "valor": formato.data(pd.Timestamp(quando)) if quando else "—", "icone": "calendario",
     "nota": "semanal, domingo de manhã"},
])

if alertas:
    ui.aviso("<b>Alertas da última validação:</b> " + " · ".join(alertas))

with ui.card("validacao_resumo"):
    ui.titulo_card("Resultado por verificação", "Linhas iguais dentro da tolerância de cada caso")
    linhas = []
    for n, r in verif.items():
        com_alerta = any(a.startswith(n + ":") for a in alertas)
        if "erro" in r:
            estado, igual = ui.estado("não correu", "falha"), "—"
        else:
            estado = ui.estado("alerta" if com_alerta else "ok", "falha" if com_alerta else "ok")
            igual = f"{pct(r):.2f} %".replace(".", ",")
        linhas.append(
            f"<tr><td><b>{r.get('titulo', n)}</b><br><small>{r.get('fonte', '')}</small></td>"
            f"<td style='text-align:right'>{formato.numero(r.get('comparados', 0))}<br><small>linhas</small></td>"
            f"<td style='text-align:right;white-space:nowrap'>{igual}<br><small>iguais</small></td><td>{estado}</td>"
            f"<td><small>{LEITURA.get(n, '')}</small></td></tr>")
    ui.html("<table style='width:100%;border-collapse:collapse;font-size:.85rem'>" + "".join(linhas) + "</table>")

with ui.card("validacao_detalhe"):
    ui.titulo_card("Detalhe", "Consulta feita à plataforma, fonte externa e diferenças encontradas")
    escolha = st.selectbox("Verificação", list(verif), format_func=lambda n: verif[n].get("titulo", n),
                           label_visibility="collapsed")
    r = verif[escolha]
    if "erro" in r:
        st.error(f"A verificação falhou: {r['erro']}")
    else:
        a, b = st.columns([3, 2], gap="medium")
        a.code(r["sql"], language="sql")
        b.markdown(f"**{r['fonte']}**")
        b.caption(r.get("url") or "")
        b.caption(f"{formato.numero(r['comparados'])} comparados · {formato.numero(r['iguais'])} iguais · "
                  f"{r['so_nosso']} só na plataforma · {r['so_fonte']} só na fonte")
        st.markdown("**Diferenças** (primeiras 15)")
        if r["divergencias"]:
            st.dataframe(pd.DataFrame(r["divergencias"]), hide_index=True, width="stretch")
        else:
            st.caption("Nenhuma.")

ui.html("<div class='nota-rodape'><b>Erros que a validação encontrou e já foram corrigidos (17/10/2026):</b> 17 "
        "bonificações que a API da B3 não lista (apareciam como quedas de 4 a 23 %); proventos de 9 emissores com "
        "barra no nome de pregão (Ambev, Klabin, ...); 819 parcelas iguais de proventos tratadas como duplicados.</div>")
ui.rodape("Fontes: IBGE (SIDRA), Banco Central (Copom, SGS, PTAX), Yahoo Finance, B3 (COTAHIST), CVM e Tesouro "
          "Transparente.")
