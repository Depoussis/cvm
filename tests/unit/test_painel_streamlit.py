"""Formatação e pesquisa do painel Streamlit (app/painel). Saltam se o ambiente não tiver as dependências da app."""
import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("streamlit")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

from painel import dados, formato  # noqa: E402


def test_numeros_no_padrao_brasileiro():
    assert formato.numero(1234567.891, 2) == "1.234.567,89"
    assert formato.pct(1.5) == "1,50 %"
    assert formato.pct(2, 1, sinal=True) == "+2,0 %"
    assert formato.brl(5.0521, 4) == "R$ 5,0521"
    assert formato.compacto(10.99e9) == "R$ 11,0 bi"
    assert formato.compacto(None) == "—"
    assert formato.mes(pd.Timestamp("2026-08-01")) == "ago/2026"


def test_cnpj_formatado():
    assert dados.formatar_cnpj("16706958000132") == "16.706.958/0001-32"


def test_busca_por_nome_sem_acentos_ticker_e_cnpj():
    cat = pd.DataFrame({"rotulo": ["KNCR11 · KINEA RENDIMENTOS · FII", "ITAÚ RENDA FIXA · FI"],
                        "cnpj": ["16706958000132", "11111111000111"]})
    cat["busca"] = cat["rotulo"].map(dados._normalizar) + " " + cat["cnpj"]
    assert list(dados.buscar(cat, "kinea rend").index) == [0]
    assert list(dados.buscar(cat, "itau").index) == [1]
    assert list(dados.buscar(cat, "kncr11").index) == [0]
    assert list(dados.buscar(cat, "16.706.958").index) == [0]
    assert len(dados.buscar(cat, "")) == 2
