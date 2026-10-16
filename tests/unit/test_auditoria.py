"""Testes sem Spark do SQL de auditoria."""
import pytest

from src.audit.reapresentacoes import TABELAS_SCD1, sql_reapresentacoes, versao_texto


def test_versao_texto_ordena_como_numero():
    assert versao_texto(9) < versao_texto(10) < versao_texto(100)
    assert len(versao_texto(5)) == 12


def test_sql_reapresentacoes_emparelha_pre_e_pos_imagem():
    sql = sql_reapresentacoes("k.silver.bcb_sgs_valores", ["serie_codigo", "data_referencia"], ["valor"], 3, 9)
    assert "table_changes('k.silver.bcb_sgs_valores', 3, 9)" in sql
    assert "_change_type = 'update_postimage'" in sql and "_change_type = 'update_preimage'" in sql
    assert "a._commit_version = d._commit_version" in sql
    assert "WHERE a.record_hash <> d.record_hash" in sql
    with pytest.raises(ValueError):
        sql_reapresentacoes("t", ["x; DROP"], ["v"], 0, 1)


def test_tabelas_scd1_sem_sobreposicao_de_chaves_e_valores():
    for tabela, (chaves, colunas) in TABELAS_SCD1.items():
        assert tabela.startswith("silver.")
        assert not set(chaves) & set(colunas)
