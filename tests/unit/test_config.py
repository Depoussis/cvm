import pytest

from src.common.config import carregar_ambiente, nome_tabela
from src.audit.control import Execucao


def test_carrega_dev():
    cfg = carregar_ambiente("dev")
    assert cfg["unity_catalog"]["catalog"] == "findata_dev"
    assert set(cfg["unity_catalog"]["schemas"]) == {"bronze", "silver", "gold", "control", "ops"}
    assert nome_tabela(cfg, "control", "pipeline_execution") == "findata_dev.control.pipeline_execution"


def test_ambiente_inexistente():
    with pytest.raises(FileNotFoundError):
        carregar_ambiente("qa-inexistente")


def test_config_sem_segredos():
    texto = str(carregar_ambiente("dev")).lower()
    for proibido in ("password", "secret", "token", "accountkey", "sharedaccesssignature"):
        assert proibido not in texto


def test_locais_geridos_e_volumes_nao_se_sobrepoem():
    uc = carregar_ambiente("dev")["unity_catalog"]
    locais = [(s["container"], s["path"]) for s in uc["schemas"].values()]
    locais += [(v["container"], "") for v in uc["volumes"].values()]
    locais.append(("control", "_catalog"))
    for i, (c1, p1) in enumerate(locais):
        for c2, p2 in locais[i + 1:]:
            if c1 != c2:
                continue
            assert p1 and p2 and not p1.startswith(p2) and not p2.startswith(p1), (c1, p1, p2)


def test_execucao_valida_modo_e_camada():
    with pytest.raises(ValueError):
        Execucao("c", "r", "p", "bcb_sgs", "selic", "bronze", "diario")
    with pytest.raises(ValueError):
        Execucao("c", "r", "p", "bcb_sgs", "selic", "platinum", "incremental")
    assert Execucao("c", "r", "p", "bcb_sgs", "selic", "bronze", "backfill").tabela == "c.control.pipeline_execution"
