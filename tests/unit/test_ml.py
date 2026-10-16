"""Validação walk-forward, métricas e backtest do modelo de ranking (src/ml/avaliacao.py)."""
import numpy as np
import pandas as pd
import pytest

from src.ml import avaliacao as av
from src.ml.features import FEATURES_ACAO, FEATURES_MACRO, SQL_FEATURES


def test_dobras_nunca_treinam_com_o_mes_de_teste_nem_o_anterior():
    meses = list(pd.date_range("2022-01-31", periods=24, freq="ME"))
    d = av.dobras(meses, minimo_treino=18, intervalo=1)
    assert [x.teste for x in d] == meses[19:]
    for x in d:
        assert max(x.treino) < x.teste
        assert x.teste - max(x.treino) > pd.Timedelta(days=40)   # salta o mês imediatamente anterior


def test_alvo_acima_da_mediana_por_data_e_nan_sem_futuro():
    df = pd.DataFrame({"data_ref": ["a"] * 4 + ["b"] * 2, "ret_fwd": [0.1, 0.2, -0.1, 0.3, np.nan, 0.0]})
    y = av.alvo(df)
    assert list(y[:4]) == [0.0, 1.0, 0.0, 1.0]
    assert np.isnan(y[4]) and y[5] == 0.0


def test_ranks_por_data():
    df = pd.DataFrame({"data_ref": ["a", "a", "b", "b"], "x": [1, 2, 100, 50]})
    assert list(av.ranks_por_data(df, ["x"])["x"]) == [0.5, 1.0, 1.0, 0.5]


def test_auc_e_ic():
    assert av.auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert av.auc([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1]) == 0.0
    assert av.auc([1, 0, 1, 0], [1, 1, 1, 1]) == 0.5
    assert av.ic(pd.Series([1, 2, 3]), pd.Series([10, 20, 30])) == pytest.approx(1.0)


def test_carteira_com_custos_e_rotacao():
    prev = pd.DataFrame({
        "data_ref": ["m1"] * 3 + ["m2"] * 3, "ticker": ["A", "B", "C", "A", "B", "C"],
        "score": [3, 2, 1, 1, 2, 3], "ret_fwd": [0.10, 0.0, -0.10, 0.05, 0.0, 0.02]})
    m = av.carteira_mensal(prev, n=1)
    assert m["ret_carteira"].round(6).tolist() == [round(0.10 - 0.001, 6), round(0.02 - 0.002, 6)]
    assert m["rotacao"].tolist() == [1.0, 1.0]
    assert m["ret_universo"].round(6).tolist() == [0.0, round(0.07 / 3, 6)]
    r = av.resumo(m)
    assert r["meses"] == 2 and r["meses_acima_universo_pct"] == 0.5 and r["max_drawdown"] == 0.0  # 1,8 % < 2,33 %


def test_sql_das_features_point_in_time():
    sql = SQL_FEATURES.format(k="cat")
    assert "{" not in sql
    assert "f.data_publicacao <= b.data_ref" in sql            # fundamentos só depois de publicados
    assert "p.data_ex <= b.data_ref" in sql                    # dividendos só depois da data ex
    assert "lead(c.preco_ajustado, 21)" in sql                 # alvo: 21 pregões à frente
    for f in FEATURES_ACAO + FEATURES_MACRO:
        assert f" AS {f}" in sql or f", {f}" in sql or f"{f}," in sql, f
