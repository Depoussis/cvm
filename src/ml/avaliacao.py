"""Validação walk-forward, métricas e backtest do modelo de ranking de ações. Só pandas/numpy (testado localmente).

Walk-forward: para cada mês de teste m, o modelo é treinado só com meses cujo alvo já era conhecido em m, deixando
um mês de intervalo (`intervalo`): o retorno dos 21 pregões depois do mês m-1 pode terminar uns dias depois de m.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

CUSTO_POR_LADO = 0.001   # 0,10 % por compra ou venda (corretagem + emolumentos + spread, aproximado)


@dataclass(frozen=True)
class Dobra:
    teste: pd.Timestamp
    treino: list[pd.Timestamp]


def dobras(datas: list[pd.Timestamp], minimo_treino: int = 18, intervalo: int = 1) -> list[Dobra]:
    """Uma dobra por mês de teste; treino = todos os meses anteriores menos os `intervalo` mais recentes."""
    datas = sorted(datas)
    saida = []
    for i, d in enumerate(datas):
        treino = datas[:max(0, i - intervalo)]
        if len(treino) >= minimo_treino:
            saida.append(Dobra(d, treino))
    return saida


def alvo(df: pd.DataFrame, data: str = "data_ref", ret: str = "ret_fwd") -> pd.Series:
    """1 se o retorno futuro ficou acima da mediana das ações na mesma data (NaN sem retorno futuro)."""
    mediana = df.groupby(data)[ret].transform("median")
    return (df[ret] > mediana).astype(float).where(df[ret].notna())


def ranks_por_data(df: pd.DataFrame, colunas: list[str], data: str = "data_ref") -> pd.DataFrame:
    """Percentil (0-1) de cada variável entre as ações da mesma data: remove o nível de mercado e outliers."""
    return df.groupby(data)[colunas].rank(pct=True)


def auc(y: np.ndarray, score: np.ndarray) -> float:
    """Área sob a curva ROC pela fórmula de Mann-Whitney (sem scikit-learn)."""
    y = np.asarray(y, dtype=float)
    s = pd.Series(np.asarray(score, dtype=float)).rank().to_numpy()
    pos, neg = (y == 1).sum(), (y == 0).sum()
    if pos == 0 or neg == 0:
        return float("nan")
    return float((s[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def ic(score: pd.Series, ret: pd.Series) -> float:
    """Information coefficient: correlação de Spearman entre a pontuação e o retorno realizado."""
    return float(pd.Series(score).rank().corr(pd.Series(ret).rank()))


def carteira_mensal(prev: pd.DataFrame, n: int = 10, data: str = "data_ref", score: str = "score",
                    ret: str = "ret_fwd") -> pd.DataFrame:
    """Por data: retorno da carteira igual-ponderada das `n` maiores pontuações, do universo e a rotação.

    Rotação = fração da carteira trocada face ao mês anterior; custo = rotação x 2 lados x CUSTO_POR_LADO
    (no primeiro mês, compra de tudo: um lado).
    """
    linhas, anterior = [], None
    for d, g in prev.dropna(subset=[ret]).sort_values(data).groupby(data):
        topo = g.nlargest(n, score)
        atual = set(topo["ticker"])
        if anterior is None:
            rotacao, custo = 1.0, CUSTO_POR_LADO
        else:
            rotacao = len(atual - anterior) / n
            custo = rotacao * 2 * CUSTO_POR_LADO
        linhas.append({data: d, "ret_carteira": topo[ret].mean() - custo, "ret_universo": g[ret].mean(),
                       "rotacao": rotacao, "custo": custo, "n_universo": len(g),
                       "auc": auc((g[ret] > g[ret].median()).astype(int), g[score]), "ic": ic(g[score], g[ret])})
        anterior = atual
    return pd.DataFrame(linhas)


def resumo(mensal: pd.DataFrame, ret_referencia: pd.Series | None = None) -> dict[str, float]:
    """Métricas agregadas de uma série mensal de backtest (retornos de ~1 mês)."""
    r = mensal["ret_carteira"].to_numpy()
    u = mensal["ret_universo"].to_numpy()
    acum = np.cumprod(1 + r)
    pico = np.maximum.accumulate(acum)
    ics = mensal["ic"].dropna()
    out = {
        "meses": float(len(mensal)),
        "auc_media": float(mensal["auc"].mean()),
        "ic_medio": float(ics.mean()),
        "ic_t": float(ics.mean() / (ics.std(ddof=1) / np.sqrt(len(ics)))) if len(ics) > 1 and ics.std() > 0 else float("nan"),
        "ic_positivo_pct": float((ics > 0).mean()),
        "ret_carteira_acum": float(acum[-1] - 1) if len(acum) else float("nan"),
        "ret_universo_acum": float(np.prod(1 + u) - 1),
        "ret_carteira_anual": float(acum[-1] ** (12 / len(r)) - 1) if len(r) else float("nan"),
        "vol_carteira_anual": float(np.std(r, ddof=1) * np.sqrt(12)) if len(r) > 1 else float("nan"),
        "max_drawdown": float((acum / pico - 1).min()) if len(acum) else float("nan"),
        "meses_acima_universo_pct": float((r > u).mean()),
        "rotacao_media": float(mensal["rotacao"].mean()),
    }
    if ret_referencia is not None and len(ret_referencia):
        out["ret_referencia_acum"] = float(np.prod(1 + np.asarray(ret_referencia, dtype=float)) - 1)
    return out
