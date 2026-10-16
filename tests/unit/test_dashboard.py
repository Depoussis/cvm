"""O painel gerado é coerente: datasets referenciados existem, nomes únicos e posições dentro da grelha de 6."""
from scripts.deploy_dashboard import DATASETS_FUNDO, painel


def test_painel_coerente():
    p = painel("findata_dev")
    nomes_ds = {d["name"] for d in p["datasets"]}
    assert len(nomes_ds) == len(p["datasets"])
    widgets = [item for pagina in p["pages"] for item in pagina["layout"]]
    nomes_w = [i["widget"]["name"] for i in widgets]
    assert len(nomes_w) == len(set(nomes_w))
    for i in widgets:
        pos = i["position"]
        assert 0 <= pos["x"] and pos["x"] + pos["width"] <= 6
        for q in i["widget"].get("queries", []):
            assert q["query"]["datasetName"] in nomes_ds
    assert all("findata_dev." in d["queryLines"][0] for d in p["datasets"])
    assert [pg["name"] for pg in p["pages"]] == ["mercado", "fundos", "analise", "operacao"]
    com_param = {d["name"] for d in p["datasets"] if d.get("parameters")}
    assert com_param == set(DATASETS_FUNDO)
    assert all(":fundo" in d["queryLines"][0] for d in p["datasets"] if d["name"] in com_param)
