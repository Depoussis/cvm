"""Os JSON do ADF são válidos e só usam variáveis que o deploy_adf.py sabe preencher."""
import json
import re
from pathlib import Path

PASTA = Path(__file__).resolve().parents[2] / "pipelines" / "azure_data_factory"
CONHECIDAS = {"env", "databricks_host", "databricks_workspace_id", "job_id_bcb", "job_id_cvm", "job_id_b3", "job_id_b3_proventos", "job_id_ml",
              "job_id_frescura", "job_id_auditoria"}


def test_json_do_adf():
    ficheiros = sorted(PASTA.rglob("*.json"))
    assert len(ficheiros) >= 6
    nomes = set()
    for f in ficheiros:
        texto = f.read_text(encoding="utf-8")
        assert set(re.findall(r"\$\{(\w+)\}", texto)) <= CONHECIDAS, f
        d = json.loads(re.sub(r"\$\{\w+\}", "x", texto))
        assert d["name"] == f.stem and "properties" in d
        nomes.add(d["name"])
    # pipelines referenciados existem
    for f in ficheiros:
        for ref in re.findall(r'"referenceName":\s*"(\w+)"', f.read_text(encoding="utf-8")):
            assert ref in nomes, (f.name, ref)


def test_gatilhos_em_hora_de_brasilia():
    for f in (PASTA / "trigger").glob("*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))["properties"]["typeProperties"]["recurrence"]
        assert r["timeZone"] == "E. South America Standard Time"
