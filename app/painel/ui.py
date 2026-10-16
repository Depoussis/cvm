"""Componentes visuais partilhados: estilo clean (fundo neutro, cards brancos com borda fina, um único
acento índigo) com modo escuro automático pelas variáveis ``light-dark()``.
"""
from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from painel import dados, formato

# Ícones de traço (24x24) usados nos cards de indicador.
ICONES = {
    "juros": '<path d="M5 19L19 5"/><circle cx="7" cy="7" r="2.2"/><circle cx="17" cy="17" r="2.2"/>',
    "cambio": '<path d="M4 8h13l-3-3M20 16H7l3 3"/>',
    "atividade": '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
    "carteira": '<path d="M3 7h16a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M3 7l12-4 2 4"/><circle cx="16.5" cy="13.5" r="1.2"/>',
    "fundos": '<rect x="3" y="4" width="7" height="7" rx="1.5"/><rect x="14" y="4" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "fluxo": '<path d="M12 3v18M7 8l5-5 5 5M7 16l5 5 5-5"/>',
    "pessoas": '<circle cx="9" cy="8" r="3.2"/><path d="M3 19c.6-3.3 3-5 6-5s5.4 1.7 6 5"/><circle cx="17" cy="9" r="2.4"/><path d="M16 14.2c2.6.2 4.4 1.8 5 4.8"/>',
    "predio": '<path d="M4 21V5l8-2v18M12 8h8v13M8 8v.01M8 12v.01M8 16v.01M16 12v.01M16 16v.01M2 21h20"/>',
    "calendario": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "camadas": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5L16 9.5"/>',
    "bolsa": '<path d="M7 3v18M17 3v18"/><rect x="4.5" y="7" width="5" height="8" rx="1"/><rect x="14.5" y="5" width="5" height="10" rx="1"/>',
    "subida": '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
}

# Pares (claro, escuro) usados em light-dark(); o Streamlit define color-scheme no .stApp conforme o tema.
CORES = {
    "--acento": ("#4F46E5", "#8B83FF"), "--acento-suave": ("#EEF0FF", "#26244A"),
    "--fundo": ("#F6F7F9", "#0F1117"), "--card": ("#FFFFFF", "#171A23"), "--borda": ("#E6E8EE", "#262A36"),
    "--divisor": ("#F0F1F5", "#20232E"), "--texto": ("#111827", "#E8EAF0"), "--suave": ("#6B7280", "#9AA1B2"),
    "--fraco": ("#9CA3AF", "#6B7280"), "--trilho": ("#F0F1F5", "#232633"), "--positivo": ("#059669", "#34D399"),
    "--negativo": ("#DC2626", "#F87171"), "--aviso": ("#B45309", "#FBBF24"),
    "--chip": ("#F3F4F6", "#232633"),
}

CSS = """
<style>
.stApp { __CORES__ }
.block-container, [data-testid="stMainBlockContainer"] { padding-top: 3.6rem; padding-bottom: 3rem; max-width: 1320px; }
h1 { font-size: 1.6rem !important; font-weight: 700 !important; letter-spacing: -0.02em; color: var(--texto); }
[data-testid="stCaptionContainer"] p { color: var(--suave); }

/* barra lateral */
[data-testid="stSidebar"] { border-right: 1px solid var(--borda); }
.marca { display: flex; align-items: center; gap: .7rem; margin: .2rem 0 1.1rem; }
.marca .logo { width: 36px; height: 36px; border-radius: 10px; background: var(--acento); color: #fff;
               display: grid; place-items: center; font-weight: 700; font-size: .9rem; }
.marca b { display: block; font-size: 1rem; color: var(--texto); line-height: 1.15; }
.marca small { color: var(--suave); font-size: .74rem; }
.snapshot { font-size: .76rem; color: var(--suave); line-height: 1.45; }
.faixa-snapshot { font-size: .74rem; color: var(--suave); margin: -.4rem 0 .9rem; padding-bottom: .55rem;
                  border-bottom: 1px solid var(--divisor); }
.faixa-snapshot b { color: var(--texto); font-weight: 600; }
.snapshot b { color: var(--texto); font-weight: 600; }

/* cabeçalho de página */
.cabecalho { display: flex; justify-content: space-between; align-items: flex-end; gap: 1rem; flex-wrap: wrap;
             margin: 0 0 1.2rem; }
.cabecalho h1 { margin: 0 !important; padding: 0 !important; }
.cabecalho p { margin: .25rem 0 0; color: var(--suave); font-size: .9rem; max-width: 760px; }
.selo { font-size: .74rem; color: var(--suave); background: var(--card); border: 1px solid var(--borda);
        border-radius: 99px; padding: .25rem .7rem; white-space: nowrap; }

/* cards de indicador */
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: .9rem; margin-bottom: 1.1rem; }
.kpi { background: var(--card); border: 1px solid var(--borda); border-radius: 14px; padding: 1rem 1.1rem;
       display: flex; gap: .85rem; align-items: flex-start; }
.kpi .icone { flex: none; width: 38px; height: 38px; border-radius: 10px; background: var(--acento-suave);
              display: grid; place-items: center; }
.kpi svg { width: 20px; height: 20px; fill: none; stroke: var(--acento); stroke-width: 1.8;
           stroke-linecap: round; stroke-linejoin: round; }
.kpi .rotulo { font-size: .78rem; color: var(--suave); line-height: 1.25; }
.kpi .valor { font-size: 1.45rem; font-weight: 700; color: var(--texto); font-variant-numeric: tabular-nums;
              letter-spacing: -0.01em; line-height: 1.3; white-space: nowrap; }
.kpi .nota { font-size: .74rem; color: var(--fraco); line-height: 1.3; }
.kpi .nota.pos { color: var(--positivo); } .kpi .nota.neg { color: var(--negativo); }

/* cards (containers com borda) */
[data-testid="stVerticalBlockBorderWrapper"], .st-key-card, [class*="st-key-card_"] {
  background: var(--card); border-color: var(--borda) !important; border-radius: 14px !important; }
.titulo-card { font-weight: 650; font-size: .95rem; color: var(--texto); margin: .1rem 0 .1rem; }
.sub-card { font-size: .78rem; color: var(--suave); margin: 0 0 .4rem; line-height: 1.35; }
[data-testid="stPlotlyChart"] { margin-top: -.2rem; }

/* ranking: colunas fixas (posição | ticker + nome | valor + barra); nome cortado com reticências */
.ranking { list-style: none; margin: .3rem 0 0; padding: 0; }
.ranking li { display: grid; grid-template-columns: 1.4rem minmax(0, 1fr) 5.8rem; align-items: center;
              gap: .7rem; padding: .5rem 0; border-bottom: 1px solid var(--divisor); }
.ranking li:last-child { border-bottom: none; }
.ranking .pos { font-size: .78rem; font-weight: 650; color: var(--fraco); text-align: right;
                font-variant-numeric: tabular-nums; }
.ranking li:nth-child(-n+3) .pos { color: var(--acento); }
.ranking .texto { min-width: 0; }
.ranking .ticker { display: block; font-size: .84rem; font-weight: 650; color: var(--texto); line-height: 1.25; }
.ranking .ticker.vazio { font-weight: 500; color: var(--fraco); font-size: .78rem; }
.ranking .nome { display: block; font-size: .76rem; color: var(--suave); white-space: nowrap; overflow: hidden;
                 text-overflow: ellipsis; line-height: 1.3; }
.ranking .valor { font-size: .85rem; font-weight: 650; text-align: right; color: var(--texto);
                  font-variant-numeric: tabular-nums; white-space: nowrap; }
.ranking .trilho { height: 4px; background: var(--trilho); border-radius: 99px; margin-top: .3rem; overflow: hidden; }
.ranking .barra { height: 100%; background: var(--acento); border-radius: 99px; margin-left: auto; opacity: .85; }

/* ficha do fundo */
.ficha { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 1rem; align-items: center; }
.ficha .nome { font-size: 1.15rem; font-weight: 700; color: var(--texto); line-height: 1.25; }
.ficha .chips { display: flex; gap: .4rem; flex-wrap: wrap; margin-top: .45rem; }
.chip { font-size: .74rem; color: var(--suave); background: var(--chip); border-radius: 99px; padding: .15rem .6rem; }
.chip.acento { color: var(--acento); background: var(--acento-suave); font-weight: 650; }
.ficha .numeros { display: flex; gap: 1.6rem; }
.ficha .numeros div { text-align: right; }
.ficha .numeros b { display: block; font-size: 1.15rem; color: var(--texto); font-variant-numeric: tabular-nums; }
.ficha .numeros small { color: var(--suave); font-size: .74rem; }

/* estado */
.estado { display: inline-flex; align-items: center; gap: .35rem; font-size: .76rem; font-weight: 650;
          padding: .15rem .55rem; border-radius: 99px; }
.estado::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.estado.ok { color: var(--positivo); background: color-mix(in srgb, var(--positivo) 12%, transparent); }
.estado.falha { color: var(--negativo); background: color-mix(in srgb, var(--negativo) 12%, transparent); }
.estado.alerta { color: var(--aviso); background: color-mix(in srgb, var(--aviso) 14%, transparent); }

.nota-rodape { font-size: .76rem; color: var(--suave); border-top: 1px solid var(--borda); margin-top: 1.8rem;
               padding-top: .7rem; line-height: 1.5; }
.aviso { font-size: .82rem; color: var(--texto); background: var(--acento-suave); border-radius: 10px;
         padding: .6rem .85rem; margin: 0 0 1rem; line-height: 1.45; }

@media (max-width: 640px) {
  .ranking li { grid-template-columns: 1.2rem minmax(0, 1fr) 5rem; gap: .5rem; }
  .ficha { grid-template-columns: 1fr; }
  .ficha .numeros { justify-content: flex-start; }
  .ficha .numeros div { text-align: left; }
}
</style>
"""


def html(conteudo: str) -> None:
    st.markdown(conteudo, unsafe_allow_html=True)


def tema() -> str:
    try:
        return "escuro" if st.context.theme.type == "dark" else "claro"
    except Exception:
        return "claro"


def aplicar_estilo() -> None:
    st.session_state["tema"] = tema()
    cores = " ".join(f"{k}: light-dark({c}, {e});" for k, (c, e) in CORES.items())
    html(CSS.replace("__CORES__", cores))


def cabecalho(titulo: str, descricao: str, selo: str | None = None) -> None:
    selo_html = f'<span class="selo">{escape(selo)}</span>' if selo else ""
    html(f'<div class="cabecalho"><div><h1>{escape(titulo)}</h1><p>{descricao}</p></div>{selo_html}</div>')


def kpis(itens: list[dict]) -> None:
    """Cada item: rotulo, valor, icone (chave de ICONES), nota opcional e tom ('pos' / 'neg')."""
    blocos = []
    for it in itens:
        icone = ICONES.get(it.get("icone", ""), ICONES["camadas"])
        nota = it.get("nota")
        nota_html = f'<div class="nota {it.get("tom", "")}">{escape(nota)}</div>' if nota else ""
        blocos.append(
            f'<div class="kpi"><div class="icone"><svg viewBox="0 0 24 24" aria-hidden="true">{icone}</svg></div>'
            f'<div><div class="rotulo">{escape(it["rotulo"])}</div><div class="valor">{escape(it["valor"])}</div>'
            f"{nota_html}</div></div>")
    html(f'<div class="kpis">{"".join(blocos)}</div>')


def titulo_card(titulo: str, sub: str | None = None) -> None:
    sub_html = f'<div class="sub-card">{sub}</div>' if sub else ""
    html(f'<div class="titulo-card">{escape(titulo)}</div>{sub_html}')


def card(chave: str):
    """Container com borda; a chave gera a classe st-key-card_<chave> usada no CSS."""
    return st.container(border=True, key=f"card_{chave}")


def ranking(df: pd.DataFrame, valor: str, fmt, titulo: str, sub: str | None = None, chave: str = "") -> None:
    """Lista ordenada com ticker, nome (cortado, nome completo no tooltip), barra proporcional e valor."""
    with card(chave or valor):
        titulo_card(titulo, sub)
        if df.empty:
            st.caption("Nenhum item cumpre os critérios.")
            return
        maximo = float(df[valor].abs().max()) or 1.0
        itens = []
        for pos, r in enumerate(df.itertuples(index=False), start=1):
            v = getattr(r, valor)
            ticker = getattr(r, "ticker", None)
            tk = (f'<span class="ticker">{escape(str(ticker))}</span>' if isinstance(ticker, str) and ticker
                  else '<span class="ticker vazio">sem ticker</span>')
            nome = escape(str(r.fundo))
            largura = max(0.0, abs(float(v)) / maximo * 100)
            itens.append(
                f'<li><span class="pos">{pos}</span><div class="texto">{tk}<span class="nome" title="{nome}">{nome}</span>'
                f'</div><div class="valor">{escape(fmt(v))}<div class="trilho"><div class="barra" '
                f'style="width:{largura:.1f}%"></div></div></div></li>')
        html(f'<ol class="ranking">{"".join(itens)}</ol>')


def estado(texto: str, tom: str) -> str:
    return f'<span class="estado {tom}">{escape(texto)}</span>'


def aviso(texto: str) -> None:
    html(f'<div class="aviso">{texto}</div>')


def rodape(fontes: str) -> None:
    m = dados.meta()
    quando = formato.data_hora(pd.Timestamp(m["exportado_em"])) if m.get("exportado_em") else "—"
    html(f'<div class="nota-rodape">{fontes} Snapshot da camada gold ({escape(m.get("catalogo", "—"))}) exportado em '
         f"{quando} (horário de Brasília).</div>")
