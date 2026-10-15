from pathlib import Path

import pytest

from src.common.sql_files import carregar_ficheiros, dividir_instrucoes, renderizar

RAIZ = Path(__file__).resolve().parents[2]


def test_renderizar_substitui_variaveis():
    assert renderizar("SELECT * FROM ${catalog}.control.t", {"catalog": "findata_dev"}) == \
        "SELECT * FROM findata_dev.control.t"


def test_renderizar_falha_sem_variavel():
    with pytest.raises(KeyError, match="catalog"):
        renderizar("CREATE TABLE ${catalog}.x (a INT)", {})


def test_dividir_ignora_ponto_e_virgula_em_strings_e_comentarios():
    sql = "-- comentário; com ponto e vírgula\nCREATE TABLE a (x STRING COMMENT 'a;b');\nSELECT 1;"
    assert dividir_instrucoes(sql) == ["CREATE TABLE a (x STRING COMMENT 'a;b')", "SELECT 1"]


def test_ddl_de_controlo_tem_as_quatro_tabelas():
    instr = [s for _, s in carregar_ficheiros(RAIZ / "sql" / "control", {"catalog": "findata_dev"})]
    criadas = {s.split()[5] for s in instr if s.upper().startswith("CREATE TABLE IF NOT EXISTS")}
    assert criadas == {
        "findata_dev.control.pipeline_execution",
        "findata_dev.control.ingestion_watermark",
        "findata_dev.control.data_quality_results",
        "findata_dev.control.source_file_registry",
    }
    assert all("${" not in s for s in instr)
