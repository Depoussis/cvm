"""Simulação de um investimento num papel da B3: compra numa data, eventos societários e proventos até hoje.

Funções puras (pandas), testadas em tests/unit/test_painel_streamlit.py.

Regras:
- Compra no primeiro pregão na data escolhida ou depois, ao preço de fecho **da época** (sem ajuste). Quantidade
  inteira (lote fracionário de 1 ação/cota); a sobra fica em caixa, sem rendimento.
- Eventos: no pregão com `fator_evento` ≠ 1 a quantidade é dividida pelo fator (desdobramento 1:2 → fator 0,5 →
  quantidade x 2; grupamento 10:1 → fator 10 → quantidade / 10; bonificação de 10 % → x 1,1). Frações que surjam
  ficam (na prática a B3 vende-as em leilão e paga em dinheiro).
- Proventos: recebe quem tem o papel no fim da data com, pelo valor por ação dessa data (base de ações da época).
  JCP com IR de 15 % na fonte, se escolhido. Reinvestimento: compra no primeiro pregão depois da data com (data ex),
  ao fecho desse dia, com quantidade fracionária.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

IR_JCP = 0.15
# IR sobre o ganho de capital na venda (pessoa física, mercado à vista, operações comuns), em 2026:
ALIQUOTA_VENDA = {"Ação": 0.15, "FII": 0.20, "ETF e fundos": 0.15}
ISENCAO_ACOES_MES = 20_000.0   # vendas de ações até R$ 20 mil no mês são isentas (não vale para FII nem ETF)


@dataclass(frozen=True)
class ImpostoVenda:
    valor_venda: float
    custo: float
    lucro: float
    aliquota: float
    imposto: float
    motivo: str


def aliquota_renda_fixa(dias: int) -> float:
    """Tabela regressiva do IR em renda fixa (ex.: Tesouro Selic), pelo prazo da aplicação."""
    return 0.225 if dias <= 180 else 0.20 if dias <= 360 else 0.175 if dias <= 720 else 0.15


def selic_liquida(retorno_bruto: float, dias: int) -> float:
    """Retorno de uma aplicação na Selic depois do IR da tabela regressiva (sem IOF nem custódia)."""
    return retorno_bruto * (1 - aliquota_renda_fixa(dias)) if retorno_bruto > 0 else retorno_bruto


def imposto_venda(classe: str, valor_venda: float, custo: float, considerar_isencao: bool = True) -> ImpostoVenda:
    """IR devido se a posição fosse toda vendida hoje (DARF do mês seguinte; sem compensar prejuízos anteriores)."""
    lucro = valor_venda - custo
    aliquota = ALIQUOTA_VENDA.get(classe, 0.15)
    if lucro <= 0:
        return ImpostoVenda(valor_venda, custo, lucro, aliquota, 0.0, "prejuízo: sem imposto (pode compensar lucros futuros)")
    if classe == "Ação" and considerar_isencao and valor_venda <= ISENCAO_ACOES_MES:
        return ImpostoVenda(valor_venda, custo, lucro, aliquota, 0.0,
                            "isento: venda de ações até R$ 20 mil no mês")
    return ImpostoVenda(valor_venda, custo, lucro, aliquota, lucro * aliquota,
                        f"{aliquota * 100:.0f} % sobre o lucro" + (" (FII não têm isenção)" if classe == "FII" else ""))


@dataclass
class Resultado:
    data_compra: pd.Timestamp
    preco_compra: float
    acoes_compradas: float
    investido: float              # acoes_compradas x preco_compra
    sobra: float                  # valor pedido - investido
    acoes_hoje: float
    preco_hoje: float
    data_hoje: pd.Timestamp
    valor_hoje: float             # acoes_hoje x preco_hoje
    proventos_recebidos: float    # líquidos de IR do JCP, se aplicável (inclui os reinvestidos)
    proventos_em_caixa: float     # não reinvestidos
    serie: pd.DataFrame           # data, acoes, preco, valor_posicao, proventos_acum, patrimonio
    eventos: pd.DataFrame         # data, fator, acoes_antes, acoes_depois, descricao
    proventos: pd.DataFrame       # data_com, data_ex, tipo, valor_por_acao, acoes, bruto, ir, liquido
    avisos: list[str] = field(default_factory=list)
    reinvestido: float = 0.0      # proventos usados para comprar mais ações (entram no custo de aquisição)

    @property
    def custo_aquisicao(self) -> float:
        """Base do IR: valor pago pelas ações (compra inicial + compras com proventos reinvestidos)."""
        return self.investido + self.reinvestido

    @property
    def total_hoje(self) -> float:
        return self.valor_hoje + self.proventos_em_caixa

    @property
    def valorizacao(self) -> float:
        """Ganho de capital: total de hoje - investido - proventos recebidos. Com reinvestimento, a valorização das
        ações compradas com proventos também conta aqui (o provento em si conta como provento)."""
        return self.total_hoje - self.investido - self.proventos_recebidos

    @property
    def retorno_total(self) -> float:
        return self.total_hoje / self.investido - 1 if self.investido else float("nan")

    @property
    def retorno_anual(self) -> float:
        anos = (self.data_hoje - self.data_compra).days / 365.25
        return (1 + self.retorno_total) ** (1 / anos) - 1 if anos > 0.08 and self.investido else float("nan")


def descrever_evento(fator: float) -> str:
    """Fator de preço → descrição para o investidor (o inverso é o que acontece à quantidade)."""
    q = 1 / fator
    if q >= 1.95 and abs(q - round(q)) < 0.02:
        return f"Desdobramento 1:{round(q)}"
    if q > 1:
        pct = (q - 1) * 100
        return f"Bonificação de {pct:.0f} %" if abs(pct - round(pct)) < 0.05 else f"Bonificação de {pct:.2f} %"
    if fator >= 1.95 and abs(fator - round(fator)) < 0.02:
        return f"Grupamento {round(fator)}:1"
    return f"Grupamento (x {q:.4f})"


def simular(precos: pd.DataFrame, proventos: pd.DataFrame, valor: float, data: pd.Timestamp,
            reinvestir: bool = False, ir_jcp: bool = True) -> Resultado:
    """precos: data, fechamento, fator_evento (um papel, ordem crescente). proventos: data_com, tipo, valor_por_acao."""
    p = precos.sort_values("data").reset_index(drop=True)
    p = p[p["fechamento"] > 0]
    a_partir = p[p["data"] >= pd.Timestamp(data)]
    if a_partir.empty:
        raise ValueError("não há pregões nesta data ou depois")
    i0 = a_partir.index[0]
    compra = p.loc[i0]
    preco_compra = float(compra["fechamento"])
    acoes = float(np.floor(valor / preco_compra))
    avisos = []
    if acoes == 0:
        avisos.append(f"O valor não chega para 1 ação a {preco_compra:,.2f}.")
    investido = acoes * preco_compra

    prov = proventos[proventos["data_com"] >= compra["data"]].sort_values("data_com").reset_index(drop=True)
    prov_i, linhas_prov, linhas_ev, serie = 0, [], [], []
    acum = caixa = 0.0
    a_reinvestir = []      # (data_com, valor) aguardam o pregão seguinte
    def creditar(ate: pd.Timestamp, inclusive: bool) -> None:
        nonlocal prov_i, acum, caixa
        while prov_i < len(prov) and (prov.at[prov_i, "data_com"] <= ate if inclusive else prov.at[prov_i, "data_com"] < ate):
            x = prov.loc[prov_i]
            bruto = acoes * float(x["valor_por_acao"])
            ir = bruto * IR_JCP if ir_jcp and str(x["tipo"]).startswith("JRS") else 0.0
            liquido = bruto - ir
            acum += liquido
            linhas_prov.append({"data_com": x["data_com"], "tipo": x["tipo"], "valor_por_acao": float(x["valor_por_acao"]),
                                "acoes": acoes, "bruto": bruto, "ir": ir, "liquido": liquido})
            if reinvestir:
                a_reinvestir.append((x["data_com"], liquido))
            else:
                caixa += liquido
            prov_i += 1

    acoes_iniciais = acoes
    for j in range(i0, len(p)):
        d, fecho, fator = p.at[j, "data"], float(p.at[j, "fechamento"]), float(p.at[j, "fator_evento"] or 1.0)
        creditar(d, inclusive=False)   # data com num dia sem pregão: vale a posição antes do evento deste pregão
        if j > i0 and abs(fator - 1) > 1e-12:              # evento entra neste pregão (data ex)
            antes = acoes
            acoes = acoes / fator
            linhas_ev.append({"data": d, "fator": fator, "acoes_antes": antes, "acoes_depois": acoes,
                              "descricao": descrever_evento(fator)})
        if j > i0 and a_reinvestir:                         # reinveste no primeiro pregão depois da data com
            total = sum(v for _, v in a_reinvestir)
            acoes += total / fecho
            for linha in linhas_prov[-len(a_reinvestir):]:
                linha["reinvestido_a"] = fecho
            a_reinvestir = []
        creditar(d, inclusive=True)    # data com hoje: a posição deste fim de dia tem direito
        serie.append({"data": d, "acoes": acoes, "preco": fecho, "valor_posicao": acoes * fecho,
                      "proventos_acum": acum, "patrimonio": acoes * fecho + caixa + sum(v for _, v in a_reinvestir)})

    ultimo = p.iloc[-1]
    s = pd.DataFrame(serie)
    return Resultado(
        data_compra=compra["data"], preco_compra=preco_compra, acoes_compradas=acoes_iniciais,
        investido=investido, sobra=valor - investido, acoes_hoje=acoes, preco_hoje=float(ultimo["fechamento"]),
        data_hoje=ultimo["data"], valor_hoje=acoes * float(ultimo["fechamento"]),
        proventos_recebidos=acum, proventos_em_caixa=caixa + sum(v for _, v in a_reinvestir), serie=s,
        reinvestido=acum - caixa - sum(v for _, v in a_reinvestir),
        eventos=pd.DataFrame(linhas_ev, columns=["data", "fator", "acoes_antes", "acoes_depois", "descricao"]),
        proventos=pd.DataFrame(linhas_prov, columns=["data_com", "tipo", "valor_por_acao", "acoes", "bruto", "ir",
                                                     "liquido", "reinvestido_a"]),
        avisos=avisos)


def referencia(precos: pd.DataFrame, valor: float, data_compra: pd.Timestamp) -> pd.DataFrame:
    """Mesmo valor aplicado num índice/ETF (preço ajustado), para comparar: data, valor."""
    p = precos[precos["data"] >= data_compra].sort_values("data")
    if p.empty:
        return pd.DataFrame(columns=["data", "valor"])
    return pd.DataFrame({"data": p["data"], "valor": valor * p["preco_ajustado"] / p["preco_ajustado"].iat[0]})


def selic_acumulada(selic_mes: pd.DataFrame, valor: float, data_compra: pd.Timestamp,
                    datas: pd.Series) -> pd.DataFrame:
    """Valor aplicado à Selic (taxa do mês em %, juros compostos mensais a partir do mês seguinte à compra)."""
    s = selic_mes.sort_values("mes")
    s = s[s["mes"] > pd.Timestamp(data_compra).to_period("M").to_timestamp()]
    fator = (1 + s["selic_mes_pct"] / 100).cumprod()
    m = pd.DataFrame({"mes": s["mes"], "valor": valor * fator.to_numpy()})
    d = pd.DataFrame({"data": pd.to_datetime(datas)}).assign(mes=lambda x: x["data"].dt.to_period("M").dt.to_timestamp())
    d = d.merge(m, on="mes", how="left")
    d["valor"] = d["valor"].ffill().fillna(valor)
    return d[["data", "valor"]]
