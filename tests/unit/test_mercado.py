"""Índices B3 e Tesouro Direto (src/ingestion/mercado.py): URLs, matriz dia x mês, CSV e janelas."""
import base64
import json
from datetime import date

import pytest

from src.ingestion import mercado as m

BASE = "https://exemplo/GetPortfolioDay/{parametros}"


def test_url_do_indice_leva_os_parametros_em_base64():
    url = m.url_indice(BASE, "IBOV", 2025)
    assert json.loads(base64.b64decode(url.rsplit("/", 1)[1])) == {"index": "IBOV", "language": "pt-br",
                                                                    "year": "2025"}


def test_matriz_dia_mes_vira_uma_linha_por_pregao():
    resposta = {"results": [{"day": 1, "rateValue1": None, "rateValue2": "125.000,10", **{f"rateValue{i}": None for i in range(3, 13)}},
                            {"day": 2, "rateValue1": "120.123,45", **{f"rateValue{i}": None for i in range(2, 13)}}]}
    linhas = m.linhas_indice(resposta, "IBOV", 2025)
    assert linhas == [{"indice": "IBOV", "ano": "2025", "mes": "2", "dia": "1", "valor": "125.000,10"},
                      {"indice": "IBOV", "ano": "2025", "mes": "1", "dia": "2", "valor": "120.123,45"}]
    with pytest.raises(ValueError, match="schema drift"):
        m.linhas_indice({"erro": 1}, "IBOV", 2025)


def test_anos_a_pedir():
    hoje = date(2026, 10, 16)
    assert m.anos_a_pedir("incremental", 2015, 2, hoje, None) == list(range(2015, 2027))   # primeira carga
    assert m.anos_a_pedir("incremental", 2015, 2, hoje, 2026) == [2025, 2026]
    assert m.anos_a_pedir("backfill", 2015, 2, hoje, 2026)[0] == 2015


CSV = ("Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;PU Compra Manha;PU Venda Manha;"
       "PU Base Manha\n"
       "Tesouro IPCA+;15/05/2035;15/10/2026;7,52;7,64;2161,47;2143,63;2143,63\n"
       "Tesouro Selic;01/03/2027;01/02/2010;0,01;0,02;4097,80;4086,80;4086,80\n").encode("latin-1")


def test_csv_do_tesouro_com_filtro_incremental():
    todas = m.linhas_tesouro(CSV)
    assert len(todas) == 2 and todas[0]["tipo_titulo"] == "Tesouro IPCA+" and todas[0]["pu_base"] == "2143,63"
    assert [x["data_base"] for x in m.linhas_tesouro(CSV, desde=date(2026, 10, 1))] == ["15/10/2026"]
    with pytest.raises(ValueError, match="schema drift"):
        m.linhas_tesouro(b"Titulo;Data\nx;y\n")
    assert m.nome_titulo("Tesouro IPCA+", date(2035, 5, 15)) == "Tesouro IPCA+ 2035"
