"""Acompanhamento ao vivo do modelo: resultado de cada ranking publicado (gold.vw_ml_acompanhamento).

Diferente do backtest: os rankings ficam gravados quando são publicados (gold.ml_ranking_historico, só inserções) e o
retorno é medido depois, com preços que ainda não existiam na altura. Retornos brutos (sem custos de transação).
"""
from __future__ import annotations

import pandas as pd

TOP_N = 10
HORIZONTE = 21


def resumir(acomp: pd.DataFrame, top_n: int = TOP_N) -> pd.DataFrame:
    """Uma linha por ranking: retorno médio do top N, do universo (todas as ações pontuadas) e do BOVA11, diferença,
    acerto (fração do top N acima da mediana do universo) e IC (Spearman entre pontuação e retorno)."""
    colunas = ["data_ref", "modelo", "publicado_em", "pregoes", "concluido", "data_fim", "ret_top", "ret_universo",
               "ret_bova11", "excesso", "acerto", "ic", "acoes"]
    if acomp.empty:
        return pd.DataFrame(columns=colunas)
    linhas = []
    for data_ref, g in acomp.groupby("data_ref"):
        acoes = g[g["posicao"].notna()]
        bova = g.loc[g["ticker"] == "BOVA11", "ret"]
        com_ret = acoes[acoes["ret"].notna()]
        top = com_ret[com_ret["posicao"] <= top_n]
        mediana = com_ret["ret"].median()
        ic = (com_ret["score"].rank().corr(com_ret["ret"].rank()) if len(com_ret) >= 10 else float("nan"))
        ret_top, ret_uni = top["ret"].mean(), com_ret["ret"].mean()
        linhas.append({
            "data_ref": data_ref, "modelo": acoes["modelo"].iat[0] if len(acoes) else None,
            "publicado_em": g["publicado_em"].min(), "pregoes": int(acoes["pregoes"].max()) if len(acoes) else 0,
            "concluido": bool(acoes["concluido"].all()) if len(acoes) else False,
            "data_fim": acoes["data_fim"].max() if len(acoes) else pd.NaT,
            "ret_top": ret_top, "ret_universo": ret_uni,
            "ret_bova11": float(bova.iat[0]) if len(bova) and pd.notna(bova.iat[0]) else float("nan"),
            "excesso": ret_top - ret_uni, "acerto": (top["ret"] > mediana).mean() if len(top) else float("nan"),
            "ic": ic, "acoes": len(acoes)})
    return pd.DataFrame(linhas, columns=colunas).sort_values("data_ref", ascending=False).reset_index(drop=True)


def placar(resumo: pd.DataFrame) -> dict:
    """Agregado dos rankings já concluídos (21 pregões)."""
    c = resumo[resumo["concluido"]]
    return {"concluidos": len(c), "em_curso": int((~resumo["concluido"]).sum()),
            "excesso_medio": c["excesso"].mean() if len(c) else float("nan"),
            "venceu_universo": (c["excesso"] > 0).mean() if len(c) else float("nan"),
            "venceu_bova11": (c["ret_top"] > c["ret_bova11"]).mean() if len(c) else float("nan"),
            "ic_medio": c["ic"].mean() if len(c) else float("nan"),
            "acerto_medio": c["acerto"].mean() if len(c) else float("nan")}
