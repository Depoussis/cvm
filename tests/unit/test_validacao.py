"""Limites da validação semanal contra fontes externas (scripts/validar_fontes.py, config/validacao.yaml)."""
from scripts.validar_fontes import avaliar_limites
from src.common.config import carregar_yaml


def _r(comparados, iguais, **extra):
    return {"comparados": comparados, "iguais": iguais, **extra}


def test_limites_do_repositorio_existem_para_todas_as_metricas():
    from scripts.validar_fontes import METRICAS, VERIFICACOES
    limites = carregar_yaml("validacao.yaml")["limites"]
    assert set(limites) <= set(VERIFICACOES)
    assert {l["metrica"] for l in limites.values() if "metrica" in l} <= set(METRICAS)


def test_alertas_abaixo_do_limite_com_erro_ou_em_falta():
    limites = {"ptax": {"min_iguais_pct": 100}, "ipca": {"min_iguais_pct": 100},
               "eventos": {"min_iguais_pct": 100, "metrica": "bonificacoes_suspeitas", "max_metrica": 0},
               "fundos": {"min_iguais_pct": 99}}
    verif = {"ptax": _r(10, 10), "ipca": _r(10, 9), "eventos": _r(5, 5, bonificacoes_suspeitas=1),
             "tesouro": {"erro": "x"}}
    alertas = avaliar_limites(verif, limites)
    assert not any(a.startswith("ptax") for a in alertas)
    assert any(a.startswith("ipca: 90.00 %") for a in alertas)
    assert any("bonificacoes_suspeitas = 1.00, máximo 0" in a for a in alertas)
    assert any(a.startswith("fundos: não correu") for a in alertas)
    assert verif["eventos"]["metricas"] == {"bonificacoes_suspeitas": 1}


def test_metrica_das_acoes_ignora_fii():
    limites = {"proventos": {"metrica": "acoes_ate_1pct_pct", "min_metrica": 85}}
    r = _r(30, 10, por_ticker=[{"classe": "Ação/ETF", "comparados": 20, "ate_1pct": 19},
                               {"classe": "FII", "comparados": 10, "ate_1pct": 0}])
    assert avaliar_limites({"proventos": r}, limites) == []
    assert r["metricas"]["acoes_ate_1pct_pct"] == 95.0
