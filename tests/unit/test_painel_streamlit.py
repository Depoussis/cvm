"""Formatação e pesquisa do painel Streamlit (app/painel). Saltam se o ambiente não tiver as dependências da app."""
import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("streamlit")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

from painel import dados, formato  # noqa: E402


def test_snapshot_remoto_so_substitui_se_for_mais_novo(tmp_path, monkeypatch):
    import json

    local, cache = tmp_path / "local", tmp_path / "cache"
    local.mkdir()
    (local / "_meta.json").write_text(json.dumps({"exportado_em": "2026-10-16T20:00:00+00:00", "linhas": {}}))
    remoto = {"_meta.json": json.dumps({"exportado_em": "2026-10-17T02:05:00+00:00", "linhas": {"ptax": 1}}).encode(),
              "ptax.parquet": b"PAR1"}
    monkeypatch.setattr(dados, "LOCAL", local)
    monkeypatch.setattr(dados, "CACHE", cache)
    monkeypatch.setattr(dados, "REMOTO", "https://exemplo")
    monkeypatch.setattr(dados, "_baixar", lambda url: remoto[url.rsplit("/", 1)[1]])
    assert dados._sincronizar() == cache and (cache / "ptax.parquet").read_bytes() == b"PAR1"

    remoto["_meta.json"] = json.dumps({"exportado_em": "2026-10-15T00:00:00+00:00", "linhas": {}}).encode()
    assert dados._sincronizar() == cache                     # remoto mais antigo: fica o que já está

    def sem_rede(url):
        raise OSError("sem rede")
    monkeypatch.setattr(dados, "_baixar", sem_rede)
    monkeypatch.setattr(dados, "CACHE", tmp_path / "vazia")
    assert dados._sincronizar() == local                     # falha: usa o snapshot do repositório


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


# ---------------------------------------------------------------- simulador de investimento
from painel import simulador  # noqa: E402


def _precos(fechos, fatores=None):
    d = pd.bdate_range("2023-05-02", periods=len(fechos))
    return pd.DataFrame({"data": d, "fechamento": fechos, "fator_evento": fatores or [1.0] * len(fechos)})


def test_compra_ao_preco_da_epoca_quantidade_inteira_e_sobra():
    r = simulador.simular(_precos([10.0, 11.0, 12.0]), pd.DataFrame(columns=["data_com", "tipo", "valor_por_acao"]),
                          1005, pd.Timestamp("2023-05-01"))   # feriado/fim de semana → primeiro pregão seguinte
    assert r.data_compra == pd.Timestamp("2023-05-02") and r.preco_compra == 10.0
    assert r.acoes_compradas == 100 and r.investido == 1000 and r.sobra == 5
    assert r.valor_hoje == 1200 and r.valorizacao == 200 and r.retorno_total == pytest.approx(0.2)
    # valorização + proventos = ganho total, com e sem reinvestimento (verificado nos outros testes)


def test_desdobramento_duplica_as_acoes_sem_mudar_o_patrimonio():
    # 1:2 no 3.º pregão: o preço cai para metade e o fator é 0,5
    r = simulador.simular(_precos([10.0, 10.0, 5.0, 5.5], [1, 1, 0.5, 1]),
                          pd.DataFrame(columns=["data_com", "tipo", "valor_por_acao"]), 1000, pd.Timestamp("2023-05-02"))
    assert r.acoes_hoje == 200 and r.valor_hoje == 1100
    assert r.eventos["acoes_antes"].tolist() == [100] and r.eventos["acoes_depois"].tolist() == [200]
    assert r.eventos["descricao"].iat[0].startswith("Desdobramento 1:2")
    assert simulador.descrever_evento(10).startswith("Grupamento 10:1")
    assert simulador.descrever_evento(1 / 1.1) == "Bonificação de 10 %"
    assert simulador.descrever_evento(1 / 1.3) == "Bonificação de 30 %"


def test_proventos_pela_posicao_na_data_com_com_ir_do_jcp():
    precos = _precos([10.0, 10.0, 10.0, 5.0], [1, 1, 1, 0.5])
    prov = pd.DataFrame({"data_com": pd.to_datetime(["2023-05-03", "2023-05-05"]),
                         "tipo": ["DIVIDENDO", "JRS CAP PROPRIO"], "valor_por_acao": [1.0, 0.5]})
    r = simulador.simular(precos, prov, 1000, pd.Timestamp("2023-05-02"), ir_jcp=True)
    # 100 ações x 1,00 de dividendo; depois do desdobramento (05/05) 200 ações x 0,50 de JCP, menos 15 %
    assert r.proventos["acoes"].tolist() == [100, 200]
    assert r.proventos_recebidos == pytest.approx(100 + 100 * 0.85)
    assert r.total_hoje == pytest.approx(200 * 5 + 185)
    sem_ir = simulador.simular(precos, prov, 1000, pd.Timestamp("2023-05-02"), ir_jcp=False)
    assert sem_ir.proventos_recebidos == pytest.approx(200)


def test_compra_depois_da_data_com_nao_recebe_e_reinvestimento_compra_no_pregao_seguinte():
    precos = _precos([10.0, 10.0, 20.0, 20.0])
    prov = pd.DataFrame({"data_com": pd.to_datetime(["2023-05-02", "2023-05-03"]), "tipo": ["DIVIDENDO"] * 2,
                         "valor_por_acao": [5.0, 2.0]})
    r = simulador.simular(precos, prov, 1000, pd.Timestamp("2023-05-03"), reinvestir=True)
    assert len(r.proventos) == 1                         # o de 02/05 era antes da compra
    assert r.acoes_hoje == pytest.approx(100 + 200 / 20)  # 200 reinvestidos a 20,00 no pregão seguinte
    assert r.proventos_em_caixa == 0 and r.proventos_recebidos == 200


def test_valorizacao_mais_proventos_igual_ao_ganho_total():
    precos = _precos([10.0, 10.0, 20.0, 18.0])
    prov = pd.DataFrame({"data_com": pd.to_datetime(["2023-05-03"]), "tipo": ["DIVIDENDO"], "valor_por_acao": [5.0]})
    for reinv in (False, True):
        r = simulador.simular(precos, prov, 1000, pd.Timestamp("2023-05-02"), reinvestir=reinv)
        assert r.valorizacao + r.proventos_recebidos == pytest.approx(r.total_hoje - r.investido)


def test_imposto_na_venda_por_classe_isencao_e_prejuizo():
    acao = simulador.imposto_venda("Ação", 25_181.04, 9_982.86)
    assert acao.aliquota == 0.15 and acao.imposto == pytest.approx((25_181.04 - 9_982.86) * 0.15)
    assert simulador.imposto_venda("Ação", 19_000, 10_000).imposto == 0          # isenção de R$ 20 mil/mês
    assert simulador.imposto_venda("Ação", 19_000, 10_000, considerar_isencao=False).imposto == pytest.approx(1_350)
    fii = simulador.imposto_venda("FII", 11_035.50, 9_959.25)
    assert fii.aliquota == 0.20 and fii.imposto == pytest.approx(1_076.25 * 0.20)  # FII: 20 %, sem isenção
    assert simulador.imposto_venda("FII", 5_000, 4_000).imposto == pytest.approx(200)
    assert simulador.imposto_venda("ETF e fundos", 5_000, 6_000).imposto == 0      # prejuízo


def test_reinvestimento_entra_no_custo_de_aquisicao():
    precos = _precos([10.0, 10.0, 20.0, 20.0])
    prov = pd.DataFrame({"data_com": pd.to_datetime(["2023-05-03"]), "tipo": ["DIVIDENDO"], "valor_por_acao": [5.0]})
    r = simulador.simular(precos, prov, 1000, pd.Timestamp("2023-05-02"), reinvestir=True)
    assert r.reinvestido == 500 and r.custo_aquisicao == 1500
    assert simulador.simular(precos, prov, 1000, pd.Timestamp("2023-05-02")).custo_aquisicao == 1000


def test_selic_liquida_pela_tabela_regressiva():
    assert simulador.aliquota_renda_fixa(100) == 0.225 and simulador.aliquota_renda_fixa(361) == 0.175
    assert simulador.aliquota_renda_fixa(1200) == 0.15
    assert simulador.selic_liquida(0.511, 1262) == pytest.approx(0.511 * 0.85)


# ---------------------------------------------------------------- carteira com aportes
from painel import carteira  # noqa: E402


def _precos_carteira(tickers_precos: dict, inicio="2024-01-02", dias=400):
    datas = pd.bdate_range(inicio, periods=dias)
    return {t: pd.DataFrame({"data": datas, "fechamento": f(range(dias)), "preco_ajustado": f(range(dias)),
                             "fator_evento": 1.0}) for t, f in tickers_precos.items()}


def test_datas_de_aporte_usam_o_ultimo_dia_nos_meses_curtos():
    d = carteira.datas_aporte(pd.Timestamp("2024-01-31"), pd.Timestamp("2024-04-15"), mensal=True)
    assert [x.strftime("%Y-%m-%d") for x in d] == ["2024-01-31", "2024-02-29", "2024-03-31"]
    assert len(carteira.datas_aporte(pd.Timestamp("2024-01-31"), pd.Timestamp("2025-01-01"), mensal=False)) == 1


def test_carteira_divide_aportes_pelos_pesos_e_leva_a_sobra_ao_aporte_seguinte():
    precos = _precos_carteira({"AAAA3": lambda r: [10.0] * len(r), "BBBB11": lambda r: [30.0] * len(r)})
    sem_prov = pd.DataFrame(columns=["data_com", "tipo", "valor_por_acao"])
    c = carteira.simular_carteira(precos, {"AAAA3": sem_prov, "BBBB11": sem_prov},
                                  {"AAAA3": "Ação", "BBBB11": "FII"}, {"AAAA3": 1, "BBBB11": 1},
                                  valor_inicial=1000, aporte_mensal=100, inicio=pd.Timestamp("2024-01-02"))
    assert len(c.aportes) == 19 and c.total_aportado == 1000 + 18 * 100
    pos = c.posicoes.set_index("ticker")
    assert pos.at["AAAA3", "acoes"] == 50 + 18 * 5                 # 500/10, depois 50/10 por mês
    # FII a 30: 500 → 16 cotas (sobra 20); cada mês 50 + sobra → compra quando chega a 30
    assert pos.at["BBBB11", "acoes"] * 30 + pos.at["BBBB11", "caixa"] == pytest.approx(500 + 18 * 50)
    assert c.imposto == 0 and c.total_liquido == pytest.approx(c.total_aportado)


def test_ir_por_classe_compensa_dentro_da_classe():
    precos = _precos_carteira({"AAAA3": lambda r: [10.0] * 200 + [20.0] * (len(r) - 200),
                      "CCCC3": lambda r: [10.0] * 200 + [6.0] * (len(r) - 200)})
    sem_prov = pd.DataFrame(columns=["data_com", "tipo", "valor_por_acao"])
    c = carteira.simular_carteira(precos, {"AAAA3": sem_prov, "CCCC3": sem_prov}, {"AAAA3": "Ação", "CCCC3": "Ação"},
                                  {"AAAA3": 1, "CCCC3": 1}, 100_000, 0, pd.Timestamp("2024-01-02"))
    imp = c.impostos["Ação"]                                      # +50 mil e −20 mil: lucro líquido de 30 mil
    assert imp.lucro == pytest.approx(30_000) and imp.imposto == pytest.approx(4_500)


def test_fluxos_no_indice_tir_e_correcao_pelo_ipca():
    aportes = pd.DataFrame({"data": pd.to_datetime(["2024-01-15", "2024-02-15"]), "valor": [100.0, 100.0]})
    taxas = pd.DataFrame({"mes": pd.date_range("2024-01-01", periods=4, freq="MS"), "cdi": [1.0] * 4,
                          "ipca": [0.5] * 4})
    cdi = carteira.indice_mensal(taxas, "cdi")
    v = carteira.aplicar_fluxos(aportes, pd.Series(pd.to_datetime(["2024-01-20", "2024-04-10"])), cdi, mensal=True)
    assert v["valor"].iat[0] == pytest.approx(100)                       # só o 1.º aporte, ainda sem juros
    assert v["valor"].iat[1] == pytest.approx(100 * 1.01 ** 3 + 100 * 1.01 ** 2)
    bruto, liquido = carteira.renda_fixa_liquida(aportes, cdi, pd.Timestamp("2024-04-10"))
    assert liquido == pytest.approx(200 + (bruto - 200) * (1 - 0.225))  # prazos < 180 dias: 22,5 %
    # IPCA divulgado com um mês de atraso: em abril corrige até março
    assert carteira.corrigido_ipca(aportes, carteira.indice_mensal(taxas, "ipca"), pd.Timestamp("2024-04-10")) == \
        pytest.approx(100 * 1.005 ** 3 + 100 * 1.005 ** 2)
    um = pd.DataFrame({"data": pd.to_datetime(["2024-01-01"]), "valor": [100.0]})
    assert carteira.tir(um, 110.0, pd.Timestamp("2024-01-01") + pd.Timedelta(days=365.25)) == pytest.approx(0.10)


# ---------------------------------------------------------------- acompanhamento ao vivo do modelo
from painel import modelo_vivo  # noqa: E402


def test_resumo_ao_vivo_top10_contra_universo_e_bova11():
    n = 20
    acoes = pd.DataFrame({"data_ref": pd.Timestamp("2026-09-30"), "ticker": [f"T{i:02d}3" for i in range(n)],
                          "score": [1 - i / n for i in range(n)], "posicao": list(range(1, n + 1)),
                          "modelo": "m v1", "publicado_em": pd.Timestamp("2026-10-01"), "pregoes": 21,
                          "concluido": True, "data_fim": pd.Timestamp("2026-10-29"),
                          "ret": [0.05 - i * 0.005 for i in range(n)]})       # retorno cai com a posição: IC = 1
    bova = acoes.iloc[[0]].assign(ticker="BOVA11", score=None, posicao=None, ret=0.01)
    curso = acoes.assign(data_ref=pd.Timestamp("2026-10-15"), pregoes=3, concluido=False, ret=0.0)
    r = modelo_vivo.resumir(pd.concat([acoes, bova, curso], ignore_index=True))
    assert list(r["data_ref"]) == [pd.Timestamp("2026-10-15"), pd.Timestamp("2026-09-30")]
    s = r.iloc[1]
    assert s["ret_top"] == pytest.approx(sum(0.05 - i * 0.005 for i in range(10)) / 10)
    assert s["ret_universo"] == pytest.approx(sum(0.05 - i * 0.005 for i in range(n)) / n)
    assert s["ret_bova11"] == pytest.approx(0.01) and s["ic"] == pytest.approx(1.0) and s["acerto"] == 1.0
    p = modelo_vivo.placar(r)
    assert p["concluidos"] == 1 and p["em_curso"] == 1 and p["venceu_universo"] == 1.0
    assert modelo_vivo.resumir(pd.DataFrame()).empty
