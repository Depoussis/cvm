"""Testes sem Spark nem rede: clientes BCB, janelas, caminhos, SQL de SCD e configuração das séries.

As respostas usadas são excertos reais das APIs (16/10/2026).
"""
from datetime import date

import pytest

from src.common import janela, raw_store
from src.common.config import carregar_yaml
from src.common.http import ClienteHttp, ErroFonte
from src.ingestion.bcb_ptax import client as ptax
from src.ingestion.bcb_sgs import client as sgs
from src.scd.merge_sql import expr_hash, merge_scd1, merge_scd2
from src.silver.common import sql_pendentes

SGS_OK = b'[{"data":"13/10/2026","valor":"0.050788"},{"data":"14/10/2026","valor":"0.050788"}]'
SGS_404 = b'{"erro":{"statusCode":404,"detail":"br.gov.bcb.pec.sgs.comum.excecoes.SGSNegocioException: Value(s) not found"}}'
PTAX_OK = (b'{"@odata.context":"x","value":[{"paridadeCompra":1.0,"paridadeVenda":1.0,"cotacaoCompra":5.0435,'
           b'"cotacaoVenda":5.04410,"dataHoraCotacao":"2026-10-14 13:05:17.833426","tipoBoletim":"Fechamento"}]}')


# ------------------------------------------------------------------ SGS

def test_janelas_respeitam_limite_e_cobrem_intervalo():
    js = sgs.janelas(date(2000, 1, 1), date(2026, 10, 16), 5)
    assert js[0] == (date(2000, 1, 1), date(2004, 12, 31))
    assert js[-1][1] == date(2026, 10, 16)
    for (a, b), (c, _) in zip(js, js[1:]):
        assert (c - b).days == 1
    assert all(b.year - a.year <= 5 for a, b in js)
    assert sgs.janelas(date(2026, 1, 2), date(2026, 1, 1), 5) == []


def test_janela_comecando_em_29_fevereiro():
    js = sgs.janelas(date(2024, 2, 29), date(2030, 1, 1), 1)
    assert js[0] == (date(2024, 2, 29), date(2025, 2, 28)) and js[1][0] == date(2025, 3, 1)


def test_parametros_sgs_formato_brasileiro():
    assert sgs.parametros(date(2026, 1, 5), date(2026, 2, 7)) == {
        "formato": "json", "dataInicial": "05/01/2026", "dataFinal": "07/02/2026"}


def test_interpretar_sgs():
    assert sgs.interpretar(200, SGS_OK)[1] == {"data": "14/10/2026", "valor": "0.050788"}
    assert sgs.interpretar(404, SGS_404) == []
    with pytest.raises(ErroFonte):
        sgs.interpretar(404, b'{"erro": "outra coisa"}')
    with pytest.raises(ErroFonte):
        sgs.interpretar(200, b'[{"data": "01/01/2026"}]')
    with pytest.raises(ErroFonte):
        sgs.interpretar(200, b'{"error": "janela"}')


def test_conversoes_sgs():
    assert sgs.converter_data("01/09/2026") == date(2026, 9, 1)
    assert str(sgs.converter_valor("-0.32")) == "-0.32"
    with pytest.raises(ValueError):
        sgs.converter_valor("n/d")


def test_series_configuradas_sao_validas_e_unicas():
    series = [sgs.Serie.de_config(s) for s in carregar_yaml("series/bcb_sgs.yaml")["series"]]
    codigos = [s.codigo for s in series]
    assert len(codigos) == len(set(codigos))
    assert {432, 11, 1, 24363} <= set(codigos)
    assert all(s.revisao_dias > 0 and s.inicio_backfill >= date(1980, 1, 1) for s in series)
    with pytest.raises(ValueError):
        sgs.Serie.de_config({"codigo": 1, "nome": "x", "periodicidade": "semanal", "inicio_backfill": "2000-01-01",
                             "permite_futuro": False, "revisao_dias": 1})


# ------------------------------------------------------------------ PTAX

def test_ptax_parametros_e_janelas():
    assert ptax.parametros_cotacao("EUR", date(2026, 10, 13), date(2026, 10, 14)) == {
        "@moeda": "'EUR'", "@dataInicial": "'10-13-2026'", "@dataFinalCotacao": "'10-14-2026'", "$format": "json"}
    js = ptax.janelas_dias(date(2015, 1, 1), date(2016, 1, 10), 366)
    assert js == [(date(2015, 1, 1), date(2016, 1, 1)), (date(2016, 1, 2), date(2016, 1, 10))]


def test_ptax_numeros_ficam_como_texto_original():
    r = ptax.interpretar(PTAX_OK, ptax.CAMPOS_COTACAO)[0]
    assert r["cotacaoVenda"] == "5.04410" and r["paridadeCompra"] == "1.0"
    with pytest.raises(ErroFonte):
        ptax.interpretar(b'{"value":[{"cotacaoCompra":1}]}', ptax.CAMPOS_COTACAO)


def test_moedas_configuradas_sem_repeticao():
    m = carregar_yaml("sources/bcb.yaml")["bcb_ptax"]["moedas"]
    assert len(m) == len(set(m)) and "USD" in m and "EUR" in m


# ------------------------------------------------------------------ HTTP

class _Resp:
    def __init__(self, status, corpo=b"[]"):
        self.status_code, self.content, self.text, self.url, self.headers = status, corpo, corpo.decode(), "u", {}


class _Sessao:
    def __init__(self, estados):
        self.estados, self.headers, self.pedidos = list(estados), {}, 0

    def request(self, metodo, url, params=None, timeout=None):
        self.pedidos += 1
        return _Resp(self.estados.pop(0))


CFG_HTTP = {"timeout_s": 1, "tentativas": 3, "backoff_base_s": 1, "pausa_entre_pedidos_s": 0, "user_agent": "t"}


def test_http_repete_em_503_e_desiste_em_400():
    esperas = []
    s = _Sessao([503, 429, 200])
    assert ClienteHttp(CFG_HTTP, s, dormir=esperas.append).get("u").status == 200
    assert s.pedidos == 3 and esperas == [1, 2]
    with pytest.raises(ErroFonte):
        ClienteHttp(CFG_HTTP, _Sessao([400]), dormir=lambda _: None).get("u")
    with pytest.raises(ErroFonte):
        ClienteHttp(CFG_HTTP, _Sessao([503, 503, 503]), dormir=lambda _: None).get("u")
    assert ClienteHttp(CFG_HTTP, _Sessao([404]), dormir=lambda _: None).get("u", aceitar=frozenset({404})).status == 404


# ------------------------------------------------------------------ janelas de execução

def test_intervalo_por_modo():
    hoje, ini = date(2026, 10, 16), date(2000, 1, 1)
    assert janela.intervalo("backfill", ini, 30, hoje) == (ini, hoje)
    assert janela.intervalo("incremental", ini, 30, hoje) == (ini, hoje)  # sem watermark
    assert janela.intervalo("incremental", ini, 30, hoje, watermark=date(2026, 10, 15)) == (date(2026, 9, 15), hoje)
    # watermark no futuro (meta Selic) não empurra o início para depois de hoje
    assert janela.intervalo("incremental", ini, 10, hoje, watermark=date(2026, 12, 1)) == (date(2026, 10, 6), hoje)
    assert janela.intervalo("reprocess", ini, 30, hoje, inicio=date(2020, 1, 1), fim=date(2020, 2, 1))[0] == date(2020, 1, 1)
    with pytest.raises(ValueError):
        janela.intervalo("reprocess", ini, 30, hoje)
    with pytest.raises(ValueError):
        janela.intervalo("diario", ini, 30, hoje)


# ------------------------------------------------------------------ raw

def test_caminho_raw_e_imutabilidade(tmp_path):
    c = raw_store.caminho_raw("findata_dev", "bcb_sgs", "serie_11", date(2026, 10, 16), "run1", "a.json")
    assert c == "/Volumes/findata_dev/ops/raw/bcb_sgs/serie_11/ingestion_date=2026-10-16/run1/a.json"
    with pytest.raises(ValueError):
        raw_store.caminho_raw("k", "bcb_sgs", "../x", date(2026, 1, 1), "r", "a.json")
    f = str(tmp_path / "x" / "a.json")
    raw_store.gravar(f, b"1")
    raw_store.gravar(f, b"1")  # repetir com o mesmo conteúdo é permitido
    with pytest.raises(FileExistsError):
        raw_store.gravar(f, b"2")


# ------------------------------------------------------------------ SQL

def test_merge_scd1():
    sql = merge_scd1("k.silver.t", "_src", ["serie_codigo", "data_referencia"], ["valor"])
    assert "t.`serie_codigo` <=> s.`serie_codigo` AND t.`data_referencia` <=> s.`data_referencia`" in sql
    assert "WHEN MATCHED AND t.record_hash <> s.record_hash THEN UPDATE" in sql
    assert "_inserted_at" in sql and "WHEN NOT MATCHED THEN INSERT" in sql


def test_merge_scd2_fecha_versao_e_insere_nova():
    sql = merge_scd2("k.silver.series", "_src", ["serie_codigo"], ["nome"])
    assert "UNION ALL" in sql and "NULL AS `_mk_serie_codigo`" in sql
    assert "t.is_current = false, t.valid_to = current_timestamp()" in sql
    assert "ON t.`serie_codigo` <=> u.`_mk_serie_codigo` AND t.is_current" in sql
    with pytest.raises(ValueError):
        merge_scd2("t", "s", ["x; DROP"], ["y"])


def test_expr_hash_distingue_nulo_de_vazio():
    assert "coalesce(cast(`a` as string), '\\u2205')" in expr_hash(["a"])


def test_sql_pendentes():
    s = sql_pendentes("k.bronze.b", "k", "bcb_sgs", "serie_1", "serie_codigo = 1", False)
    assert "NOT IN" in s and "execution_status = 'SUCCEEDED'" in s and "entity_name = 'serie_1'" in s
    assert "NOT IN" not in sql_pendentes("k.bronze.b", "k", "bcb_sgs", "serie_1", "true", True)
