"""Gera e publica o painel AI/BI (Lakeview) "Findata · Mercado, fundos e operação" no workspace Databricks.

Uso:  python scripts/deploy_dashboard.py --env dev
Escreve dashboards/findata_<env>.lvdash.json (versionado) e cria/atualiza o painel em /Workspace/Shared/findata_<env>.
As consultas correm no SQL Warehouse serverless do ambiente (2X-Small, auto-stop 1 min) só quando o painel é aberto.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from databricks.sdk import WorkspaceClient  # noqa: E402
from databricks.sdk.service.dashboards import Dashboard  # noqa: E402

from src.common.config import carregar_ambiente  # noqa: E402

log = logging.getLogger("deploy_dashboard")
NOME = "Findata · Mercado, fundos e operação"


def datasets(k: str) -> dict[str, str]:
    g, c = f"{k}.gold", f"{k}.control"
    return {
        "kpi_mercado": f"""
            SELECT max(CASE WHEN serie_codigo = 432 THEN valor END) AS meta_selic,
                   max(CASE WHEN serie_codigo = 24363 THEN valor END) AS ibc_br,
                   (SELECT cotacao_venda FROM {g}.fct_ptax_diario WHERE simbolo = 'USD' ORDER BY data_cotacao DESC LIMIT 1) AS ptax_usd,
                   (SELECT cotacao_venda FROM {g}.fct_ptax_diario WHERE simbolo = 'EUR' ORDER BY data_cotacao DESC LIMIT 1) AS ptax_eur
            FROM {g}.vw_serie_ultimo_valor""",
        "selic": f"""
            SELECT CAST(trunc(data_referencia, 'MM') AS DATE) AS data, CAST(max_by(valor, data_referencia) AS DOUBLE) AS valor,
                   CASE serie_codigo WHEN 432 THEN 'Meta Selic (Copom)' ELSE 'Selic efetiva anualizada' END AS serie
            FROM {g}.fct_serie_valor WHERE serie_codigo IN (432, 1178) AND data_referencia <= current_date()
            GROUP BY 1, 3""",
        "ptax": f"""
            SELECT data_cotacao AS data, simbolo, CAST(cotacao_venda AS DOUBLE) AS cotacao_venda
            FROM {g}.fct_ptax_diario WHERE simbolo IN ('USD', 'EUR', 'GBP')""",
        "cambio_mensal": f"""
            SELECT mes, simbolo, variacao_pct FROM {g}.vw_cambio_mensal
            WHERE mes >= add_months(trunc(current_date(), 'MM'), -12) AND simbolo IN ('USD', 'EUR', 'GBP', 'JPY', 'CHF')""",
        "ibc": f"""SELECT data_referencia AS mes, CAST(valor AS DOUBLE) AS ibc_br FROM {g}.fct_serie_valor
                   WHERE serie_codigo = 24363 AND data_referencia >= DATE'2015-01-01'""",
        "kpi_fundos": f"""
            SELECT fundos, pl_total_bi, cotistas, captacao_liquida_bi, mes FROM {g}.vw_industria_fundos_mensal
            WHERE mes = (SELECT max(mes) FROM {g}.vw_industria_fundos_mensal WHERE mes < trunc(current_date(), 'MM'))""",
        "industria": f"""SELECT mes, pl_total_bi, captacao_liquida_bi FROM {g}.vw_industria_fundos_mensal
                        WHERE mes < trunc(current_date(), 'MM')""",
        "vs_selic": f"""
            SELECT mes, classificacao, pct_acima_selic, rentab_mediana_pct, selic_mes_pct, fundos
            FROM {g}.vw_fundos_vs_selic
            WHERE classificacao IN ('Renda Fixa', 'Multimercado', 'Ações', 'Cambial') AND mes < trunc(current_date(), 'MM')""",
        "top_pl": f"""
            SELECT posicao, denominacao_social AS fundo, classificacao, administrador,
                   round(vl_patrim_liq / 1e9, 2) AS pl_bi, nr_cotst AS cotistas, dt_comptc AS data
            FROM {g}.vw_fundos_maiores_pl WHERE posicao <= 20""",
        "execucoes": f"""
            SELECT dia, pipeline_name AS pipeline, execution_status AS estado, execucoes, lidos, escritos, rejeitados,
                   duracao_media_s FROM {g}.vw_execucoes_resumo WHERE dia >= date_sub(current_date(), 14)""",
        "qualidade": f"""
            SELECT ultima, table_name AS tabela, rule_name AS regra, severity AS severidade, registos_falhados
            FROM {g}.vw_qualidade_resumo WHERE result = 'FAILED' AND dia >= date_sub(current_date(), 14)""",
        "reconciliacao": f"""
            SELECT source_system AS fonte, resultado, count(*) AS entidades, sum(registos_fonte) AS registos_fonte,
                   sum(valores_diferentes + so_na_fonte + so_na_plataforma) AS divergencias, max(executed_at) AS quando
            FROM {c}.reconciliation_results
            WHERE executed_at = (SELECT max(executed_at) FROM {c}.reconciliation_results r2
                                 WHERE r2.source_system = reconciliation_results.source_system
                                   AND r2.entity_name = reconciliation_results.entity_name)
            GROUP BY ALL""",
        "frescura": f"""
            SELECT source_system AS fonte, entity_name AS entidade, watermark_value AS ultima_data,
                   datediff(current_date(), to_date(watermark_value)) AS dias, last_full_reconciliation AS reconciliado
            FROM {c}.ingestion_watermark WHERE watermark_type = 'reference_date'""",
    }


def campos(*nomes: str) -> list[dict]:
    return [{"name": n, "expression": f"`{n}`"} for n in nomes]


def widget(nome: str, ds: str, cols: list[str], spec: dict, pos: tuple[int, int, int, int]) -> dict:
    x, y, w, h = pos
    return {"widget": {"name": nome, "queries": [{"name": "main_query", "query": {
                "datasetName": ds, "fields": campos(*cols), "disaggregated": True}}], "spec": spec},
            "position": {"x": x, "y": y, "width": w, "height": h}}


def contador(nome, ds, col, titulo, pos):
    return widget(nome, ds, [col], {"version": 2, "widgetType": "counter",
                                    "encodings": {"value": {"fieldName": col, "displayName": titulo}},
                                    "frame": {"showTitle": True, "title": titulo}}, pos)


ROTULOS = {"data": "Data", "mes": "Mês", "valor": "% a.a.", "cotacao_venda": "R$", "variacao_pct": "Variação (%)",
           "ibc_br": "Índice", "pl_total_bi": "R$ bi", "captacao_liquida_bi": "R$ bi", "pct_acima_selic": "% dos fundos",
           "rentab_mediana_pct": "% no mês", "serie": "Série", "simbolo": "Moeda", "classificacao": "Classificação"}


def linha(nome, ds, x, y, cor, titulo, pos, tipo="line", x_tipo="temporal"):
    enc = {"x": {"fieldName": x, "scale": {"type": x_tipo}, "displayName": ROTULOS.get(x, x)},
           "y": {"fieldName": y, "scale": {"type": "quantitative"}, "displayName": ROTULOS.get(y, y)}}
    cols = [x, y]
    if cor:
        enc["color"] = {"fieldName": cor, "scale": {"type": "categorical"}, "displayName": ROTULOS.get(cor, cor)}
        cols.append(cor)
    return widget(nome, ds, cols, {"version": 3, "widgetType": tipo, "encodings": enc,
                                   "frame": {"showTitle": True, "title": titulo}}, pos)


def tabela(nome, ds, cols, titulo, pos):
    return widget(nome, ds, cols, {"version": 1, "widgetType": "table", "encodings": {"columns": [
        {"fieldName": c, "displayName": c, "visible": True, "order": i, "type": "string", "displayAs": "string",
         "title": c, "booleanValues": ["false", "true"], "alignContent": "left"} for i, c in enumerate(cols)]},
        "frame": {"showTitle": True, "title": titulo}}, pos)


def texto(nome, linhas, pos):
    x, y, w, h = pos
    return {"widget": {"name": nome, "multilineTextboxSpec": {"lines": [linha_ + "\n\n" for linha_ in linhas]}},
            "position": {"x": x, "y": y, "width": w, "height": h}}


def painel(k: str) -> dict:
    mercado = [
        texto("t_mercado", ["## Juros e câmbio", "Fonte: Banco Central do Brasil (SGS e PTAX). Atualizado pelo ADF nos dias úteis."], (0, 0, 6, 2)),
        contador("k_selic", "kpi_mercado", "meta_selic", "Meta Selic (% a.a.)", (0, 2, 2, 3)),
        contador("k_usd", "kpi_mercado", "ptax_usd", "PTAX USD (venda)", (2, 2, 2, 3)),
        contador("k_eur", "kpi_mercado", "ptax_eur", "PTAX EUR (venda)", (4, 2, 2, 3)),
        linha("l_selic", "selic", "data", "valor", "serie", "Selic desde 2000, fim de mês (% a.a.)", (0, 5, 3, 7)),
        linha("l_ptax", "ptax", "data", "cotacao_venda", "simbolo", "PTAX de venda (R$)", (3, 5, 3, 7)),
        linha("l_cambio", "cambio_mensal", "mes", "variacao_pct", "simbolo",
              "Variação mensal da PTAX de fim de mês (%), 12 meses", (0, 12, 3, 7)),
        linha("l_ibc", "ibc", "mes", "ibc_br", None, "IBC-Br (índice)", (3, 12, 3, 7)),
    ]
    fundos = [
        texto("t_fundos", ["## Fundos de investimento", "Fonte: CVM, informe diário (classes, sem subclasses). "
                           "Rentabilidade = variação da cota de fim de mês; % acima da Selic compara com a Selic acumulada no mês (SGS 4390). "
                           "Só fundos com PL ≥ R$ 10 mi. **PL e captação somados incluem fundos de cotas (FIC), que aplicam noutros fundos: há dupla contagem, por isso não são o PL da indústria.**"], (0, 0, 6, 2)),
        contador("k_pl", "kpi_fundos", "pl_total_bi", "PL somado (R$ bi, com dupla contagem FIC)", (0, 2, 2, 3)),
        contador("k_fundos", "kpi_fundos", "fundos", "Fundos/classes com informe", (2, 2, 2, 3)),
        contador("k_capt", "kpi_fundos", "captacao_liquida_bi", "Captação líquida somada no mês (R$ bi)", (4, 2, 2, 3)),
        linha("l_pl", "industria", "mes", "pl_total_bi", None, "PL somado dos fundos/classes (R$ bi, com dupla contagem FIC)", (0, 5, 3, 7)),
        linha("b_capt", "industria", "mes", "captacao_liquida_bi", None, "Captação líquida somada por mês (R$ bi)", (3, 5, 3, 7), tipo="bar"),
        linha("l_vs_selic", "vs_selic", "mes", "pct_acima_selic", "classificacao", "% de fundos acima da Selic no mês",
              (0, 12, 3, 7)),
        linha("l_mediana", "vs_selic", "mes", "rentab_mediana_pct", "classificacao", "Rentabilidade mediana no mês (%)",
              (3, 12, 3, 7)),
        tabela("tb_top", "top_pl", ["posicao", "fundo", "classificacao", "administrador", "pl_bi", "cotistas", "data"],
               "20 maiores fundos por património líquido", (0, 19, 6, 9)),
    ]
    operacao = [
        texto("t_op", ["## Operação e qualidade", "Execuções, regras de qualidade que falharam (14 dias), "
                       "última reconciliação com as fontes e frescura dos dados."], (0, 0, 6, 2)),
        tabela("tb_rec", "reconciliacao", ["fonte", "resultado", "entidades", "registos_fonte", "divergencias", "quando"],
               "Reconciliação com a fonte (última por entidade)", (0, 2, 3, 6)),
        tabela("tb_fresc", "frescura", ["fonte", "entidade", "ultima_data", "dias", "reconciliado"],
               "Frescura (watermarks)", (3, 2, 3, 6)),
        tabela("tb_exec", "execucoes", ["dia", "pipeline", "estado", "execucoes", "lidos", "escritos", "rejeitados",
                                        "duracao_media_s"], "Execuções (14 dias)", (0, 8, 6, 8)),
        tabela("tb_dq", "qualidade", ["ultima", "tabela", "regra", "severidade", "registos_falhados"],
               "Regras de qualidade com falhas (INFO só regista; CRITICAL/HIGH bloqueiam a gold)", (0, 16, 6, 8)),
    ]
    return {
        "datasets": [{"name": n, "displayName": n, "queryLines": [" ".join(q.split())]} for n, q in datasets(k).items()],
        "pages": [{"name": "mercado", "displayName": "Mercado (BCB)", "layout": mercado},
                  {"name": "fundos", "displayName": "Fundos (CVM)", "layout": fundos},
                  {"name": "operacao", "displayName": "Operação e qualidade", "layout": operacao}],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="dev")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = carregar_ambiente(args.env)
    w = WorkspaceClient(host=cfg["databricks"]["host"], auth_type="azure-cli")
    wh = next(x for x in w.warehouses.list() if x.name == cfg["databricks"]["sql_warehouse_name"])
    conteudo = json.dumps(painel(cfg["unity_catalog"]["catalog"]), ensure_ascii=False, indent=1)
    destino = RAIZ / "dashboards" / f"findata_{args.env}.lvdash.json"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(conteudo, encoding="utf-8", newline="\n")

    pasta = f"/Workspace/Shared/findata_{args.env}"
    sem_prefixo = lambda c: (c or "").removeprefix("/Workspace")  # noqa: E731 (a API devolve com ou sem o prefixo)
    # a listagem não traz o caminho; confirma-se com get
    existente = next((d for d in (w.lakeview.get(x.dashboard_id) for x in w.lakeview.list() if x.display_name == NOME)
                      if sem_prefixo(d.parent_path) == sem_prefixo(pasta)), None)
    painel_ = Dashboard(display_name=NOME, serialized_dashboard=conteudo, warehouse_id=wh.id, parent_path=pasta)
    if existente:
        d = w.lakeview.update(existente.dashboard_id, painel_)
    else:
        d = w.lakeview.create(painel_)
    w.lakeview.publish(d.dashboard_id, warehouse_id=wh.id, embed_credentials=True)
    log.info("painel publicado: %s/dashboardsv3/%s/published", cfg["databricks"]["host"], d.dashboard_id)


if __name__ == "__main__":
    main()
