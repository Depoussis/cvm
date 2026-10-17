"""Simulação de uma carteira com aportes: vários papéis com pesos, aporte inicial e aportes mensais.

Funções puras (pandas), testadas em tests/unit/test_painel_streamlit.py. Reutiliza ``simulador.simular`` lote a lote.

Regras:
- Cada aporte é dividido pelos pesos e cada parte compra o papel no primeiro pregão na data do aporte ou depois,
  em quantidade inteira. A sobra de cada papel fica em caixa e entra no aporte seguinte desse papel.
- Aportes mensais no mesmo dia do mês da data inicial (no último dia, em meses mais curtos).
- IR na venda por classe (ações, FII, ETF), com lucros e prejuízos do mesmo mês compensados dentro da classe; a
  isenção de R$ 20 mil vale para o total vendido em ações.
- Comparações com os mesmos fluxos de caixa: cada aporte aplicado no CDI, na Selic ou no BOVA11 na mesma data.
- Retorno real: os aportes corrigidos pelo IPCA até hoje são o valor que só manteria o poder de compra.
- TIR: taxa anual que iguala os aportes ao total líquido de hoje (rentabilidade ponderada pelo dinheiro).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from painel import simulador


@dataclass
class Carteira:
    data_inicio: pd.Timestamp
    data_hoje: pd.Timestamp
    aportes: pd.DataFrame        # data, valor (total aportado nessa data)
    posicoes: pd.DataFrame       # ticker, classe, peso, aportado, custo, acoes, preco, valor_hoje, proventos, caixa
    serie: pd.DataFrame          # data, aportado, patrimonio
    impostos: dict[str, simulador.ImpostoVenda]
    avisos: list[str] = field(default_factory=list)

    @property
    def total_aportado(self) -> float:
        return float(self.aportes["valor"].sum())

    @property
    def total_bruto(self) -> float:
        p = self.posicoes
        return float((p["valor_hoje"] + p["proventos_em_caixa"] + p["caixa"]).sum())

    @property
    def imposto(self) -> float:
        return sum(i.imposto for i in self.impostos.values())

    @property
    def total_liquido(self) -> float:
        return self.total_bruto - self.imposto


def datas_aporte(inicio: pd.Timestamp, fim: pd.Timestamp, mensal: bool) -> list[pd.Timestamp]:
    """Data inicial e, se mensal, o mesmo dia de cada mês seguinte até ``fim`` (último dia em meses curtos)."""
    inicio, fim = pd.Timestamp(inicio), pd.Timestamp(fim)
    datas = [inicio]
    if mensal:
        k = 1
        while (d := inicio + pd.DateOffset(months=k)) <= fim:
            datas.append(d)
            k += 1
    return datas


def simular_carteira(precos: dict[str, pd.DataFrame], proventos: dict[str, pd.DataFrame], classes: dict[str, str],
                     pesos: dict[str, float], valor_inicial: float, aporte_mensal: float, inicio: pd.Timestamp,
                     reinvestir: bool = False, ir_jcp: bool = True, isencao: bool = True) -> Carteira:
    """precos/proventos/classes por ticker (como em ``simulador.simular``); pesos somam 1 (normalizados aqui)."""
    soma = sum(pesos.values())
    pesos = {t: p / soma for t, p in pesos.items() if p > 0}
    fim = min(precos[t]["data"].max() for t in pesos)
    datas = datas_aporte(inicio, fim, aporte_mensal > 0)
    fluxos = [(d, valor_inicial if i == 0 else aporte_mensal) for i, d in enumerate(datas)]
    avisos, linhas, series = [], [], []

    for t, peso in pesos.items():
        p = precos[t]
        caixa, lotes = 0.0, []
        primeiro = p.loc[p["fechamento"] > 0, "data"].min()
        if primeiro > pd.Timestamp(inicio) + pd.Timedelta(days=7):
            avisos.append(f"{t} só tem cotações desde {primeiro:%d/%m/%Y}: os aportes anteriores compram nessa data.")
        for d, v in fluxos:
            montante = v * peso + caixa
            if p.loc[p["data"] >= d].empty:
                caixa = montante
                continue
            r = simulador.simular(p, proventos[t], montante, d, reinvestir=reinvestir, ir_jcp=ir_jcp)
            caixa = r.sobra
            if r.acoes_compradas > 0:
                lotes.append(r)
        if not lotes:
            avisos.append(f"{t}: o valor de cada aporte não chega para comprar 1 unidade; fica em caixa.")
        s = _somar_series([lt.serie[["data", "patrimonio"]] for lt in lotes])
        series.append(s.assign(ticker=t))
        linhas.append({
            "ticker": t, "classe": classes[t], "peso": peso,
            "aportado": sum(v * peso for _, v in fluxos),
            "custo": sum(lt.custo_aquisicao for lt in lotes),
            "acoes": sum(lt.acoes_hoje for lt in lotes),
            "preco": float(p["fechamento"].iat[-1]) if len(p) else float("nan"),
            "valor_hoje": sum(lt.valor_hoje for lt in lotes),
            "proventos": sum(lt.proventos_recebidos for lt in lotes),
            "proventos_em_caixa": sum(lt.proventos_em_caixa for lt in lotes),
            "caixa": caixa,
        })

    posicoes = pd.DataFrame(linhas)
    impostos = {}
    for classe, g in posicoes.groupby("classe"):
        impostos[classe] = simulador.imposto_venda(classe, float(g["valor_hoje"].sum()), float(g["custo"].sum()),
                                                   isencao)
    patrimonio = (pd.concat(series).pivot_table(index="data", columns="ticker", values="patrimonio", aggfunc="sum")
                  .sort_index().ffill().fillna(0.0).sum(axis=1))
    aportes = pd.DataFrame(fluxos, columns=["data", "valor"])
    aportado = aportes.set_index("data")["valor"].cumsum().reindex(patrimonio.index, method="ffill").fillna(0.0)
    serie = pd.DataFrame({"data": patrimonio.index, "aportado": aportado.to_numpy(), "patrimonio": patrimonio.to_numpy()})
    return Carteira(data_inicio=pd.Timestamp(datas[0]), data_hoje=fim, aportes=aportes, posicoes=posicoes,
                    serie=serie, impostos=impostos, avisos=avisos)


def _somar_series(partes: list[pd.DataFrame]) -> pd.DataFrame:
    if not partes:
        return pd.DataFrame(columns=["data", "patrimonio"])
    m = pd.concat([x.set_index("data")["patrimonio"].rename(i) for i, x in enumerate(partes)], axis=1)
    return m.sort_index().ffill().fillna(0.0).sum(axis=1).rename("patrimonio").reset_index()


# ---------------------------------------------------------------- índices e comparações com os mesmos fluxos

def indice_mensal(taxas: pd.DataFrame, coluna: str) -> pd.Series:
    """Índice acumulado por mês a partir de taxas mensais em %: I(m) = prod_{k<=m}(1 + r_k), com base 1 no mês
    anterior ao primeiro (para um aporte nesse mês ser corrigido desde o início)."""
    t = taxas[["mes", coluna]].dropna().sort_values("mes")
    meses = pd.DatetimeIndex(t["mes"])
    base = pd.Series([1.0], index=[meses[0] - pd.DateOffset(months=1)]) if len(meses) else pd.Series(dtype=float)
    return pd.concat([base, pd.Series((1 + t[coluna].to_numpy() / 100).cumprod(), index=meses)])


def _no_mes(indice: pd.Series, datas: pd.Series) -> np.ndarray:
    """Valor do índice no mês de cada data (o último disponível, se o mês ainda não saiu)."""
    meses = pd.to_datetime(pd.Series(datas)).dt.to_period("M").dt.to_timestamp()
    return _no_dia(indice, meses)


def _no_dia(indice: pd.Series, datas) -> np.ndarray:
    """Último valor do índice na data ou antes (o primeiro, para datas anteriores ao início)."""
    s = indice.sort_index()
    pos = s.index.searchsorted(pd.DatetimeIndex(pd.to_datetime(pd.Series(datas))), side="right") - 1
    return s.to_numpy()[np.clip(pos, 0, len(s) - 1)]


def aplicar_fluxos(aportes: pd.DataFrame, datas: pd.Series, indice: pd.Series, mensal: bool) -> pd.DataFrame:
    """Valor em cada data de aplicar cada aporte no índice: sum v_i x I(t) / I(d_i), só para d_i <= t.

    mensal=True: índice por mês (CDI, Selic; capitaliza a partir do mês seguinte ao aporte, como o simulador de um
    papel). mensal=False: índice diário (preço ajustado de um ETF), na data ou no último pregão antes dela.
    """
    datas = pd.to_datetime(pd.Series(datas)).reset_index(drop=True)
    if mensal:
        it, ia = _no_mes(indice, datas), _no_mes(indice, aportes["data"])
    else:
        it, ia = _no_dia(indice, datas), _no_dia(indice, aportes["data"])
    d = datas.to_numpy()[:, None]
    ativo = aportes["data"].to_numpy()[None, :] <= d
    valor = (aportes["valor"].to_numpy()[None, :] * it[:, None] / ia[None, :] * ativo).sum(axis=1)
    return pd.DataFrame({"data": datas, "valor": valor})


def renda_fixa_liquida(aportes: pd.DataFrame, indice: pd.Series, data_final: pd.Timestamp) -> tuple[float, float]:
    """(bruto, líquido) de aplicar cada aporte num índice mensal de renda fixa e resgatar tudo em ``data_final``.

    Cada aporte paga IR pela tabela regressiva do seu próprio prazo (sem IOF nem custódia)."""
    i_fim = _no_mes(indice, [data_final])[0]
    i_ap = _no_mes(indice, aportes["data"])
    v = aportes["valor"].to_numpy()
    final = v * i_fim / i_ap
    dias = (pd.Timestamp(data_final) - aportes["data"]).dt.days.to_numpy()
    aliq = np.array([simulador.aliquota_renda_fixa(int(x)) for x in dias])
    ganho = final - v
    return float(final.sum()), float((v + np.where(ganho > 0, ganho * (1 - aliq), ganho)).sum())


def tesouro_mesmos_aportes(aportes: pd.DataFrame, titulo: pd.DataFrame, datas: pd.Series,
                           data_final: pd.Timestamp) -> tuple[pd.DataFrame, float, float, list[str]]:
    """Cada aporte compra o título Tesouro Direto (frações) ao PU de compra da primeira data base na data do aporte
    ou depois; vale o PU de venda (recompra pelo Tesouro) em cada data. Devolve (série data/valor, bruto, líquido
    de IR pela tabela regressiva de cada aporte, avisos). Sem taxa de custódia da B3 nem cupões (usar títulos sem
    juros semestrais)."""
    t = titulo.dropna(subset=["pu_compra", "pu_venda"]).sort_values("data")
    avisos = []
    if t.empty:
        return pd.DataFrame(columns=["data", "valor"]), float("nan"), float("nan"), ["título sem preços"]
    idx = t["data"].searchsorted(aportes["data"].to_numpy(), side="left")
    fora = idx >= len(t)
    if fora.any():
        avisos.append(f"{int(fora.sum())} aporte(s) depois do último preço do título ficam de fora.")
    if (aportes["data"] < t["data"].iat[0] - pd.Timedelta(days=7)).any():
        avisos.append(f"O título só tem preços desde {t['data'].iat[0]:%d/%m/%Y}: os aportes anteriores compram nessa data.")
    idx = np.clip(idx, 0, len(t) - 1)
    unidades = np.where(fora, 0.0, aportes["valor"].to_numpy() / t["pu_compra"].to_numpy()[idx])
    datas_compra = t["data"].to_numpy()[idx]
    pu = pd.Series(t["pu_venda"].to_numpy(), index=pd.DatetimeIndex(t["data"]))
    d = pd.to_datetime(pd.Series(datas)).reset_index(drop=True)
    pu_t = _no_dia(pu, d)
    ativo = datas_compra[None, :] <= d.to_numpy()[:, None]
    serie = pd.DataFrame({"data": d, "valor": (unidades[None, :] * ativo).sum(axis=1) * pu_t})
    final = unidades * _no_dia(pu, [data_final])[0]
    v = np.where(fora, 0.0, aportes["valor"].to_numpy())
    dias = (pd.Timestamp(data_final) - pd.to_datetime(datas_compra)).days.to_numpy()
    aliq = np.array([simulador.aliquota_renda_fixa(int(x)) for x in dias])
    ganho = final - v
    return serie, float(final.sum()), float((v + np.where(ganho > 0, ganho * (1 - aliq), ganho)).sum()), avisos


def corrigido_ipca(aportes: pd.DataFrame, ipca: pd.Series, data_hoje: pd.Timestamp) -> float:
    """Aportes corrigidos pela inflação até hoje: quanto seria preciso ter só para manter o poder de compra.

    O IPCA de um mês só sai no mês seguinte; usa-se o índice até ao mês anterior a cada data."""
    ant = lambda ds: pd.to_datetime(pd.Series(ds)) - pd.DateOffset(months=1)  # noqa: E731
    i_hoje = _no_mes(ipca, ant([data_hoje]))[0]
    i_ap = _no_mes(ipca, ant(aportes["data"]))
    return float((aportes["valor"].to_numpy() * i_hoje / i_ap).sum())


def tir(aportes: pd.DataFrame, valor_final: float, data_final: pd.Timestamp) -> float:
    """Taxa interna de retorno anual (bisseção): sum v_i (1+r)^((T - d_i)/365.25) = valor_final."""
    anos = ((pd.Timestamp(data_final) - aportes["data"]).dt.total_seconds() / 86400 / 365.25).to_numpy()
    v = aportes["valor"].to_numpy()
    if v.sum() <= 0 or anos.max() < 30 / 365.25:
        return float("nan")
    f = lambda r: (v * (1 + r) ** anos).sum() - valor_final  # noqa: E731
    a, b = -0.99, 10.0
    if f(a) > 0 or f(b) < 0:
        return float("nan")
    for _ in range(100):
        m = (a + b) / 2
        a, b = (m, b) if f(m) < 0 else (a, m)
    return (a + b) / 2
