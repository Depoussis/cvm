"""B3 COTAHIST: layout de largura fixa, URLs, ficheiros a verificar e validação do cabeçalho/trailer."""
import io
import zipfile
from datetime import date

import pytest

from src.common.config import carregar_yaml
from src.ingestion.b3 import cotahist

# linha real do COTAHIST_D15102026 (PETR4)
PETR4 = ("012026101502PETR4       010PETROBRAS   PN      N2   R$  000000000576000000000058090000000005709000000000576900"
         "000000057360000000005733000000000574071528000000000037576500000000216815612400000000000000009999123100000010"
         "000000000000BRPETRACNPR6230")
CFG = carregar_yaml("datasets/b3.yaml")["cotahist"]


def test_layout_cobre_as_245_posicoes_sem_buracos():
    assert len(PETR4) == cotahist.TAMANHO_LINHA
    fim = 0
    for _, ini, f in cotahist.LAYOUT:
        assert ini == fim + 1
        fim = f
    assert fim == cotahist.TAMANHO_LINHA


def test_parse_linha_real():
    r = cotahist.parse_linha(PETR4)
    assert (r["data_pregao"], r["codbdi"], r["codneg"], r["tpmerc"]) == ("20261015", "02", "PETR4", "010")
    assert r["nomres"] == "PETROBRAS" and r["especi"] == "PN      N2" and r["codisi"] == "BRPETRACNPR6"
    assert cotahist.valor("preult", r["preult"]) == 57.36
    assert cotahist.valor("voltot", r["voltot"]) == 2168156124.0
    assert cotahist.valor("totneg", r["totneg"]) == 71528
    assert cotahist.valor("fatcot", r["fatcot"]) == 1
    assert cotahist.valor("prazot", r["prazot"]) is None


def test_expressoes_spark_usam_as_mesmas_posicoes():
    exprs = cotahist.expressoes_spark()
    assert exprs[3] == "rtrim(substring(linha, 13, 12)) AS codneg"
    assert len(exprs) == len(cotahist.LAYOUT)


def test_alvos_por_modo():
    hoje = date(2026, 10, 16)  # sexta-feira
    anuais = cotahist.alvos("backfill", CFG, hoje)
    assert anuais[0] == ("https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A2021.ZIP", "2021")
    assert anuais[-1][1] == "2026"
    diarios = cotahist.alvos("incremental", CFG, hoje)
    assert diarios[-1] == ("https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D16102026.ZIP", "2026-10-16")
    assert all(date.fromisoformat(p).weekday() < 5 for _, p in diarios)
    assert [p for _, p in cotahist.alvos("reprocess", CFG, hoje, date(2023, 5, 1), date(2024, 1, 1))] == ["2023", "2024"]
    with pytest.raises(ValueError):
        cotahist.alvos("reprocess", CFG, hoje)


def test_envelope_e_trailer():
    cab = "00COTAHIST.2026BOVESPA 20261015".ljust(245)
    trailer = "99COTAHIST.2026BOVESPA 2026101500000018827".ljust(245)
    assert cotahist.validar_envelope(cab, trailer, 18827) == []
    assert cotahist.validar_envelope(cab, trailer, 18825) == []          # leitura do layout (inclui 00 e 99)
    assert "trailer indica" in cotahist.validar_envelope(cab, trailer, 18000)[0]
    assert cotahist.validar_envelope(cab, "", 1)  # ficheiro truncado: sem trailer


def test_extrair_txt_em_blocos_e_rejeita_zip_inesperado():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("COTAHIST_D15102026.TXT", PETR4 + "\r\n")
    destino = io.BytesIO()
    assert cotahist.extrair_txt(buf.getvalue(), destino) == "COTAHIST_D15102026.TXT"
    assert destino.getvalue().startswith(b"012026101502PETR4")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.TXT", "x")
        z.writestr("b.TXT", "y")
    with pytest.raises(ValueError):
        cotahist.extrair_txt(buf.getvalue(), io.BytesIO())
