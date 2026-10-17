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


def test_ler_envelope_em_fluxo():
    corpo = ("00COTAHIST.2026BOVESPA 20261015".ljust(245) + "\r\n" + PETR4 + "\r\n" + PETR4 + "\r\n"
             + "99COTAHIST.2026BOVESPA 2026101500000000002".ljust(245) + "\r\n").encode("latin-1")
    cab, trailer, n = cotahist.ler_envelope(io.BytesIO(corpo))
    assert n == 2 and cab.startswith("00COTAHIST") and trailer.startswith("99")
    assert cotahist.validar_envelope(cab, trailer, n) == []


def test_chave_liga_txt_do_auto_loader_ao_zip_registado():
    zip_ = "/Volumes/c/ops/raw/b3/cotahist/ingestion_date=2026-10-16/job-1/COTAHIST_A2021.ZIP"
    txt = "dbfs:/Volumes/c/ops/raw/b3/cotahist/ingestion_date=2026-10-16/job-1/extraidos/COTAHIST_A2021.TXT"
    assert cotahist.chave_ficheiro(zip_) == cotahist.chave_ficheiro(txt)
    assert cotahist.chave_ficheiro(zip_).endswith("/JOB-1/COTAHIST_A2021")
    assert "upper(regexp_replace(" in cotahist.chave_ficheiro_sql("p")


def test_calculo_gold_reutilizado_pela_carga_incremental_e_pela_verificacao():
    from src.gold.cotacoes import calculo, sql_diferencas
    sql = calculo("cat", "SELECT * FROM s", "data_pregao >= d0")
    assert "FROM (SELECT * FROM s) s" in sql and sql.rstrip().endswith("WHERE data_pregao >= d0")
    assert "NOT LIKE 'IBO%'" in sql
    # eventos oficiais da B3 têm prioridade sobre a heurística
    assert "cat.silver.b3_evento_acao" in sql and "WHEN fator_oficial IS NOT NULL THEN fator_oficial" in sql
    assert "1.0 / (1.0 + fator / 100.0)" in sql      # desdobramento/bonificação em %
    assert "1.0 / fator" in sql                      # grupamento em fração
    dif = sql_diferencas("cat")
    assert "FULL OUTER JOIN cat.gold.fct_cotacao_diaria" in dif and "FROM cat.silver.b3_cotacao_diaria" in dif


def test_bonificacoes_complementares_entram_como_eventos_oficiais():
    from src.gold.cotacoes import bonificacoes_complementares, sql_fator_oficial
    linhas = bonificacoes_complementares()
    # bonificação de 10 % do Itaú (data com 17/03/2025) que a API da B3 não lista
    assert {"emissor": "ITUB", "data_com": date(2025, 3, 17), "percentual": 10} in linhas
    assert len({(b["emissor"], b["data_com"]) for b in linhas}) == len(linhas)
    sql = sql_fator_oficial("cat")
    assert "('ITUB', DATE'2025-03-17', 10.0)" in sql
    assert "LEFT ANTI JOIN" in sql      # se a B3 publicar o mesmo evento, vale o oficial


def test_proventos_urls_numeros_e_datas():
    import base64, json
    from decimal import Decimal
    from src.ingestion.b3 import proventos as pv
    u = pv.url_dinheiro("PETROBRAS", 2)
    assert json.loads(base64.b64decode(u.rsplit("/", 1)[1])) == {
        "language": "pt-br", "pageNumber": 2, "pageSize": 120, "tradingName": "PETROBRAS"}
    # com a barra a API devolve 0 registos (Ambev, Klabin, Light...): validação contra o Yahoo, 17/10/2026
    u = pv.url_dinheiro("AMBEV S/A", 1)
    assert json.loads(base64.b64decode(u.rsplit("/", 1)[1]))["tradingName"] == "AMBEV SA"
    assert pv.url_complemento("PETR").endswith(base64.b64encode(b'{"issuingCompany":"PETR","language":"pt-br"}').decode())
    assert pv.numero("0,67407131") == Decimal("0.67407131")
    assert pv.numero("1.234,5") == Decimal("1234.5")
    assert pv.numero("") is None and pv.numero("abc") is None
    assert pv.data_br("21/08/2026") == date(2026, 8, 21) and pv.data_br("31/12/9999") == date(9999, 12, 31)
    assert pv.data_br("") is None
    assert pv.chaves_em_falta({"typeStock": "ON"}, {"typeStock", "valueCash"}) == {"valueCash"}
    assert pv.paginas({"page": {"totalPages": 3}}) == 3 and pv.paginas({}) == 0


def test_registo_de_provento_para_a_bronze():
    from src.ingestion.b3 import proventos as pv
    api = {"typeStock": "ON", "dateApproval": "06/08/2026", "valueCash": "0,67407131", "ratio": "1",
           "corporateAction": "JRS CAP PROPRIO", "lastDatePriorEx": "21/08/2026", "closingPricePriorExDate": "49,34",
           "quotedPerShares": "1", "campoNovo": "x"}
    r = pv.registo("dinheiro", api, emissor="PETR")
    assert r["emissor"] == "PETR" and r["tipo_acao"] == "ON" and r["valor"] == "0,67407131"
    assert r["data_com"] == "21/08/2026" and r["data_hora_com"] is None and "campoNovo" not in r
    assert pv.chaves_em_falta(api, pv.CHAVES_DINHEIRO) == set()


def test_regras_de_contas_dos_fundamentos():
    import re
    from src.gold import fundamentos as f
    sql = f.SQL_FUNDAMENTOS.format(k="cat")       # sem chavetas soltas
    assert "cat.silver.cvm_demo_conta" in sql and "{" not in sql
    py = lambda r: re.compile(r.replace("(?i)", ""), re.I)  # noqa: E731
    assert py(f.RE_LUCRO).search("Lucro/Prejuízo Consolidado do Período")
    assert py(f.RE_LUCRO).search("Lucro ou Prejuízo Líquido do Exercício")
    assert not py(f.RE_LUCRO).search("Lucro por Ação - (R$ / Ação)")
    assert py(f.RE_CONTROLADORA).search("Atribuído a Sócios da Empresa Controladora")
    assert not py(f.RE_CONTROLADORA).search("Atribuído a Sócios Não Controladores")
    assert py(f.RE_PL).search("Patrimônio Líquido Consolidado") and py(f.RE_NAO_CONTROLADORES).search(
        "Participação dos Acionistas Não Controladores")
    assert py(f.RE_CAIXA).search("Caixa e Equivalentes de Caixa") and py(f.RE_CAIXA).search("Aplicações Financeiras")


def test_fii_url_e_registo_dos_rendimentos_exatos():
    import base64, json
    from src.ingestion.b3 import proventos as pv
    u = pv.url_fundo("KNCR")
    assert "/fundsProxy/fundsCall/GetListedSupplementFunds/" in u
    assert json.loads(base64.b64decode(u.rsplit("/", 1)[1])) == {"cnpj": "0", "identifierFund": "KNCR", "typeFund": 7}
    x = {"assetIssued": "BRKNCRCTF000", "paymentDate": "14/10/2026", "rate": "1,13000000000",
         "relatedTo": "SETEMBRO 2026/2026", "approvedOn": "30/09/2026", "isinCode": "BRKNCRCTF000",
         "label": "RENDIMENTO", "lastDatePrior": "30/09/2026", "remarks": ""}
    assert not pv.chaves_em_falta(x, pv.CHAVES_FII)
    r = pv.registo("fii", x, fundo="KNCR")
    assert r["fundo"] == "KNCR" and r["isin"] == "BRKNCRCTF000" and r["data_com"] == "30/09/2026"
    assert pv.numero(r["valor"]) == pv.numero("1,13") and r["referencia"] == "SETEMBRO 2026/2026"
