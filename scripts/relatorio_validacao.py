"""Gera docs/validacao/relatorio.html a partir de docs/validacao/resultado.json (scripts/validar_fontes.py).

Uso:  python scripts/relatorio_validacao.py

Uma secção por verificação: a consulta à plataforma, a fonte externa, os totais, uma amostra lado a lado e as
divergências com a explicação. As imagens de docs/img/validacao são capturas destas secções.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ENTRADA = RAIZ / "docs" / "validacao" / "resultado.json"
SAIDA = RAIZ / "docs" / "validacao" / "relatorio.html"

# Conclusão de cada verificação (o porquê das diferenças), escrita depois de investigar cada caso.
NOTAS = {
    "ptax": "Todas as cotações de compra e venda do dólar e do euro desde 2015 são iguais às do Banco Central, à "
            "sexta casa decimal.",
    "selic": "As 11 diferenças e os 3 dias sem par caem em feriados nacionais (Corpus Christi, Tiradentes, Finados, "
             "Independência) ou fins de semana. Nesses dias, a página do Copom e a API SGS do próprio BCB usam "
             "convenções diferentes para o início da vigência. Em todos os 14 dias o valor da plataforma é igual ao "
             "da API SGS, de onde a série vem.",
    "ipca": "Os 321 meses do IPCA desde 2000 são iguais aos publicados pelo IBGE, uma fonte independente do Banco "
            "Central.",
    "cotacoes": "Fecho do último ano, ao cêntimo: 98,8 % iguais ao Yahoo. Nos 58 dias diferentes, o fecho da "
                "plataforma é igual ao do ficheiro oficial da B3 (COTAHIST_D, descarregado de novo) em 58 de 58; o "
                "do Yahoo, em 0. Os 19 pregões sem par no Yahoo são dias que faltam no Yahoo (ex.: 10/08/2026). Retorno "
                "diário desde 2021: 98,5 % iguais a 0,11 pp, e as diferenças aparecem aos pares (o Yahoo regista outro "
                "preço num dia e volta ao certo no seguinte) ou no dia em que o Yahoo ajusta um FII por direitos de "
                "subscrição.",
    "proventos": "Ações: ABEV3, B3SA3, ITUB4, SUZB3, VALE3 e WEGE3 batem a 100 %. RENT3 difere em 3,7 % constantes: a "
                 "plataforma ajusta à bonificação de 12/2025 publicada pela B3 e o Yahoo não. BBDC4 difere 0,17 % "
                 "(ajuste próprio do Yahoo). PETR4 em 22/11/2022: a plataforma tem R$ 3,35 por ação (dividendo de "
                 "R$ 1,60 + R$ 1,16 + JCP), como anunciado pela Petrobras; o Yahoo só R$ 1,75. FII: desde 17/10/2026 "
                 "a plataforma usa o valor exato da B3 nos últimos ~12 meses (iguais ao Yahoo); antes disso, a "
                 "estimativa pelo informe mensal da CVM (DY x cota patrimonial), por isso compara-se por mês e só se "
                 "espera proximidade.",
    "eventos": "Os 66 desdobramentos, grupamentos e bonificações das 100 ações mais negociadas desde 2021 têm o mesmo "
               "fator que no Yahoo, depois da correção de 17/10/2026 (17 bonificações que faltavam na API da B3). Os "
               "4 só da plataforma são eventos oficiais recentes da B3 (AXIA, CYRE3, RENT3) que o Yahoo não tem.",
    "indices": "94,4 % dos dias iguais a 1 ponto e 100 % a 1 %. Nos 164 dias diferentes, a variação do dia da "
               "plataforma está mais perto da do ETF BOVA11 (que replica o Ibovespa) em 122 dias; a do Yahoo, em 42. O "
               "erro médio da plataforma nesses dias (0,15 pp) é o normal de todos os dias (0,16 pp); o do Yahoo é "
               "quase o dobro (0,26 pp). O Yahoo tem fechos errados sobretudo em 2019 e 2020.",
    "fundos": "99,99 % das 538 mil linhas de setembro são iguais ao ficheiro da CVM. As 57 diferenças e as 27 linhas "
              "novas são informes que os administradores corrigiram ou entregaram depois da última carga: o ficheiro "
              "da CVM foi reescrito em {ficheiro_cvm_modificado}, depois da carga de {ultima_carga_plataforma}. A "
              "carga seguinte deteta a reapresentação e atualiza essas linhas (docs/auditoria.md).",
    "tesouro": "As 177 mil linhas de preços e taxas do Tesouro Direto desde 2002 são iguais ao CSV original. Os 29 "
               "preços a zero que a fonte publica em 2010 contam como sem preço dos dois lados.",
}
ORDEM = ["ptax", "selic", "ipca", "indices", "cotacoes", "eventos", "proventos", "fundos", "tesouro"]
ROTULOS = {"_nosso": "plataforma", "_fonte": "fonte", "_dif": "diferença"}


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if abs(v) >= 1000:
            return f"{v:,.2f}".replace(",", " ").replace(".", ",")
        return f"{v:.6g}".replace(".", ",")
    return html.escape(str(v))


def _cabecalho(c: str) -> str:
    for suf, rot in ROTULOS.items():
        if c.endswith(suf):
            return f"{html.escape(c[: -len(suf)])}<br><small>{rot}</small>"
    return html.escape(c)


def _tabela(linhas: list[dict], maximo: int = 8) -> str:
    if not linhas:
        return "<p class='vazio'>nenhuma</p>"
    cols = list(linhas[0])
    cab = "".join(f"<th>{_cabecalho(c)}</th>" for c in cols)
    corpo = "".join("<tr>" + "".join(f"<td>{_fmt(r.get(c))}</td>" for c in cols) + "</tr>" for r in linhas[:maximo])
    return f"<table><thead><tr>{cab}</tr></thead><tbody>{corpo}</tbody></table>"


def _kpis(v: dict) -> str:
    pct = 100 * v["iguais"] / max(v["comparados"], 1)
    itens = [("comparados", f"{v['comparados']:,}".replace(",", " ")), ("iguais", f"{pct:.2f} %".replace(".", ",")),
             ("diferentes", str(v["diferentes"])), ("só na plataforma", str(v["so_nosso"])),
             ("só na fonte", str(v["so_fonte"]))]
    return "<div class='kpis'>" + "".join(
        f"<div class='kpi'><span>{r}</span><b>{x}</b></div>" for r, x in itens) + "</div>"


def _extra(nome: str, v: dict) -> str:
    if nome == "selic":
        return "<h4>Desempate: valor da API SGS nesses dias</h4>" + _tabela(v["desempate_sgs"], 14)
    if nome == "indices":
        d = v["desempate_bova11"]
        return ("<h4>Desempate com o ETF BOVA11 nos dias diferentes</h4>" + _tabela([{
            "dias": d["dias"], "plataforma mais perto": d["nosso_mais_perto"], "Yahoo mais perto": d["yahoo_mais_perto"],
            "erro médio plataforma (pp)": round(d["erro_medio_nosso_pp"], 3),
            "erro médio Yahoo (pp)": round(d["erro_medio_yahoo_pp"], 3),
            "erro médio, todos os dias (pp)": round(d["erro_medio_todos_os_dias_pp"], 3)}]))
    if nome == "cotacoes":
        d, r = v["desempate_cotahist"], v["retorno"]
        return ("<h4>Desempate com o ficheiro oficial da B3 (COTAHIST_D) nos dias diferentes</h4>" + _tabela([{
            "dias": d["dias"], "plataforma = ficheiro B3": d["nosso_igual_ficheiro"],
            "Yahoo = ficheiro B3": d["yahoo_igual_ficheiro"]}]) + _tabela(d["exemplos"], 6) +
            f"<h4>Retorno diário, {r['periodo']}</h4>" + _tabela([{
                "comparados": r["comparados"], "iguais (0,11 pp)": r["iguais"],
                "%": round(100 * r["iguais"] / r["comparados"], 2)}]))
    if nome == "proventos":
        return "<h4>Por papel</h4>" + _tabela(v["por_ticker"], 20)
    if nome == "eventos" and v.get("exemplos_so_nosso"):
        return "<h4>Só na plataforma (eventos oficiais da B3)</h4>" + _tabela(v["exemplos_so_nosso"])
    if nome == "fundos":
        return "<h4>Linhas novas no ficheiro da CVM depois da carga</h4>" + _tabela(v["exemplos_so_fonte"], 5)
    return ""


def secao(nome: str, v: dict) -> str:
    nota = NOTAS[nome].format(**{k: v.get(k, "") for k in ("ficheiro_cvm_modificado", "ultima_carga_plataforma")})
    indep = "fonte independente" if v["independente"] else "mesma origem, descarregada de novo"
    periodo = f" · {v['periodo']}" if v.get("periodo") else ""
    return f"""
<section id="{nome}">
  <header><h2>{html.escape(v['titulo'])}</h2><span class="tag">{indep}</span></header>
  {_kpis(v)}
  <div class="duas">
    <div><h3>Consulta na plataforma</h3><pre>{html.escape(v['sql'])}</pre></div>
    <div><h3>Fonte externa</h3><p><b>{html.escape(v['fonte'])}</b></p><p class="url">{html.escape(v['url'] or '')}</p>
      <p class="pequeno">Chave da comparação: {', '.join(v['chave'])}{periodo} · verificado em {v['verificado_em']}</p></div>
  </div>
  <h3>Amostra lado a lado (últimas linhas)</h3>{_tabela(v['amostra'])}
  <h3>Divergências</h3>{_tabela(v['divergencias'])}
  {_extra(nome, v)}
  <p class="nota">{html.escape(nota)}</p>
</section>"""


VEREDITOS = {
    "ptax": "igual", "selic": "diferenças só em feriados; igual à API SGS", "ipca": "igual",
    "indices": "diferenças são erros do Yahoo (desempate BOVA11)",
    "cotacoes": "diferenças são erros do Yahoo (58/58 iguais ao ficheiro da B3)",
    "eventos": "igual depois da correção de 17/10", "proventos": "ações iguais salvo convenções do Yahoo; FII exatos desde 10/2025",
    "fundos": "diferenças são revisões da CVM depois da carga", "tesouro": "igual",
}


def resumo(r: dict) -> str:
    def n_(x: int) -> str:
        return f"{x:,}".replace(",", " ")

    def p_(v: dict) -> str:
        return f"{100 * v['iguais'] / max(v['comparados'], 1):.2f} %".replace(".", ",")
    linhas = "".join(
        f"<tr><td>{html.escape(r[n]['titulo'])}</td><td>{html.escape(r[n]['fonte'])}</td>"
        f"<td>{n_(r[n]['comparados'])}</td><td>{p_(r[n])}</td><td>{html.escape(VEREDITOS[n])}</td></tr>"
        for n in ORDEM if n in r)
    return (f"<section id='resumo'><header><h2>Resumo da validação</h2></header><table><thead><tr><th>Dados</th>"
            f"<th>Comparado com</th><th>Linhas</th><th>Iguais</th><th>Conclusão</th></tr></thead><tbody>{linhas}"
            f"</tbody></table></section>")


CSS = """
body{font-family:Inter,Segoe UI,Arial,sans-serif;background:#f4f6fa;color:#1d2433;margin:0;padding:24px}
section{background:#fff;border:1px solid #e3e7ef;border-radius:14px;padding:22px 26px;margin:0 auto 24px;max-width:1180px}
header{display:flex;align-items:center;gap:12px;margin-bottom:10px}
h2{font-size:20px;margin:0}h3{font-size:14px;margin:18px 0 6px;color:#46506a}h4{font-size:13px;margin:16px 0 6px;color:#46506a}
.tag{font-size:12px;background:#eef2ff;color:#3842a8;border-radius:20px;padding:3px 10px}
.kpis{display:flex;gap:10px;margin:8px 0 4px}.kpi{flex:1;background:#f7f9fc;border:1px solid #e8ecf3;border-radius:10px;padding:10px 12px}
.kpi span{display:block;font-size:12px;color:#6b7590}.kpi b{font-size:20px}
.duas{display:grid;grid-template-columns:1.25fr 1fr;gap:18px}
pre{background:#0f172a;color:#e2e8f0;border-radius:10px;padding:12px 14px;font-size:12px;white-space:pre-wrap;margin:0}
.url{font-family:Consolas,monospace;font-size:11px;word-break:break-all;color:#4a5578}.pequeno{font-size:12px;color:#6b7590}
table{border-collapse:collapse;width:100%;font-size:12px;margin-bottom:6px}
th{background:#f1f4f9;text-align:left;padding:6px 8px;border-bottom:1px solid #dde3ec;font-weight:600}
th small{font-weight:400;color:#6b7590}td{padding:5px 8px;border-bottom:1px solid #eef1f6;font-variant-numeric:tabular-nums}
.nota{background:#f0fdf4;border:1px solid #c9ecd5;border-radius:10px;padding:12px 14px;font-size:13px;line-height:1.5;margin-top:16px}
.vazio{color:#6b7590;font-size:12px}
#resumo td:nth-child(3),#resumo td:nth-child(4){white-space:nowrap}
"""


def main() -> None:
    r = json.loads(ENTRADA.read_text(encoding="utf-8"))["verificacoes"]
    corpo = resumo(r) + "".join(secao(n, r[n]) for n in ORDEM if n in r)
    SAIDA.write_text(f"<!doctype html><html lang='pt'><head><meta charset='utf-8'><title>Validação dos dados</title>"
                     f"<style>{CSS}</style></head><body>{corpo}</body></html>", encoding="utf-8")
    print(f"relatório em {SAIDA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
