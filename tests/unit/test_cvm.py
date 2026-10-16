"""Testes sem Spark nem rede dos utilitários CVM. Cabeçalhos e amostras são reais (16/10/2026)."""
import io
import zipfile
from datetime import date, datetime

import pytest

from src.bronze.csv_loader import ddl_tabela
from src.common.config import carregar_yaml
from src.ingestion.cvm import files as cvm
from src.scd.merge_sql import fechar_ausentes_scd2

CFG = carregar_yaml("datasets/cvm.yaml")
INF = CFG["datasets"]["fi_inf_diario"]
V2 = (b"TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;ID_SUBCLASSE;DT_COMPTC;VL_TOTAL;VL_QUOTA;VL_PATRIM_LIQ;CAPTC_DIA;RESG_DIA;NR_COTST\n"
      b"CLASSES - FIF;00.017.024/0001-53;;2026-09-01;1107741.39;44.636723400000;1214792.63;0.00;0.00;1\n")
V1 = (b"TP_FUNDO;CNPJ_FUNDO;DT_COMPTC;VL_TOTAL;VL_QUOTA;VL_PATRIM_LIQ;CAPTC_DIA;RESG_DIA;NR_COTST\n"
      b"FI;00.017.024/0001-53;2021-01-04;1097664.87;27.503335800000;1095773.57;0.00;0.00;1\n")


def _zip(ficheiros: dict[str, bytes]) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for nome, dados in ficheiros.items():
            z.writestr(nome, dados)
    return b.getvalue()


def test_meses():
    assert cvm.meses("2025-11", date(2026, 2, 3)) == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert cvm.meses("2026-03", date(2026, 2, 3)) == []
    assert cvm.url_mes(INF["url"], "2026-09").endswith("/inf_diario_fi_202609.zip")


def test_meses_por_modo():
    hoje = date(2026, 10, 16)
    backfill = cvm.meses_a_verificar("backfill", INF, hoje)
    assert backfill[0] == "2024-01" and backfill[-1] == "2026-10"
    inc = cvm.meses_a_verificar("incremental", INF, hoje)
    assert len(inc) == INF["revisao_meses"] and inc[-1] == "2026-10"
    assert cvm.meses_a_verificar("reprocess", INF, hoje, "2020-11", "2021-02") == ["2021-01", "2021-02"]
    with pytest.raises(ValueError):
        cvm.meses_a_verificar("reprocess", INF, hoje)


def test_contrato_reconhece_as_duas_versoes_do_informe():
    versoes = INF["ficheiros"]["inf_diario"]["versoes"]
    assert cvm.identificar_versao(cvm.cabecalho(V2, "UTF-8"), versoes) == "v2"
    assert cvm.identificar_versao(cvm.cabecalho(V1, "UTF-8"), versoes) == "v1"
    assert cvm.identificar_versao(["TP_FUNDO", "CNPJ_FUNDO", "NOVA_COLUNA"], versoes) is None
    cols = cvm.colunas_bronze(versoes)
    assert cols[:3] == ["tp_fundo", "cnpj_fundo", "dt_comptc"] and "cnpj_fundo_classe" in cols
    assert len(cols) == len(set(cols)) == 12


def test_cabecalho_com_bom_e_crlf():
    assert cvm.cabecalho(b"\xef\xbb\xbfA;B\r\n1;2", "UTF-8") == ["A", "B"]


def test_codificacao():
    assert cvm.detectar_codificacao("SÃO PAULO".encode("utf-8")) == "UTF-8"
    assert cvm.detectar_codificacao("SÃO PAULO".encode("latin-1")) == "ISO-8859-1"


def test_extrair_zip_filtra_e_protege_caminhos():
    z = _zip({"inf_diario_fi_202609.csv": V2, "leia-me.txt": b"x"})
    assert [n for n, _ in cvm.extrair_zip(z, "inf_diario_fi_*.csv")] == ["inf_diario_fi_202609.csv"]
    with pytest.raises(ValueError):
        cvm.extrair_zip(_zip({"../fora.csv": b"x"}), "*.csv")


def test_mudou():
    anterior = {"source_etag": '"abc"', "source_last_modified": datetime(2026, 10, 10, 3, 0)}
    assert not cvm.mudou('"abc"', None, anterior)
    assert cvm.mudou('"def"', None, anterior)
    assert cvm.mudou(None, None, None)
    sem_etag = {"source_etag": None, "source_last_modified": datetime(2026, 10, 10, 3, 0)}
    assert not cvm.mudou(None, "Sat, 10 Oct 2026 03:00:00 GMT", sem_etag)
    assert cvm.mudou(None, "Fri, 16 Oct 2026 03:54:44 GMT", sem_etag)
    assert cvm.data_http("Fri, 16 Oct 2026 03:54:44 GMT") == datetime(2026, 10, 16, 3, 54, 44)


def test_contratos_da_config():
    for nome, ds in CFG["datasets"].items():
        assert ds["pacote_ckan"] in CFG["ckan"]["pacotes"], nome
        for f in ds["ficheiros"].values():
            for v in f["versoes"].values():
                assert len(v) == len(set(v))
    pessoais = CFG["dados_pessoais"]
    cols_fundo = cvm.colunas_bronze(CFG["datasets"]["fi_registro"]["ficheiros"]["registro_fundo"]["versoes"])
    assert set(pessoais["cvm_fi_registro_fundo"]) <= set(cols_fundo)
    cols_cia = cvm.colunas_bronze(CFG["datasets"]["cia_aberta_cad"]["ficheiros"]["cad_cia_aberta"]["versoes"])
    assert set(pessoais["cvm_cia_aberta_cad"]) <= set(cols_cia)


def test_ddl_bronze():
    ddl = ddl_tabela("k.bronze.t", ["a", "b_c"], "coment'ario", ["_reference_period"])
    assert "`a` STRING" in ddl and "_corrupt_record STRING" in ddl and "CLUSTER BY (_reference_period)" in ddl
    assert "comentario" in ddl
    with pytest.raises(ValueError):
        ddl_tabela("t", ["a; DROP"], "x", [])


def test_fechar_ausentes():
    sql = fechar_ausentes_scd2("k.silver.cia", "_src", ["cd_cvm"])
    assert "LEFT ANTI JOIN _src" in sql and "t.is_current = false" in sql
