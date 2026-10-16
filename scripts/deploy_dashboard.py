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


CNPJ_SEL = "regexp_extract(:fundo, '([0-9]{14})$', 1)"
TIPO_SEL = "regexp_extract(:fundo, ' · (FII|FI) · ', 1)"
DATASETS_FUNDO = ["sel_ficha", "sel_rentab", "sel_pl", "sel_dy", "sel_cota"]


def datasets(k: str) -> dict[str, str]:
    g, c = f"{k}.gold", f"{k}.control"
    mes_fechado = "trunc(current_date(), 'MM')"
    return {
        "fii_kpi": f"""
            SELECT count(*) AS fiis, count(DISTINCT segmento) AS segmentos,
                   round(sum(patrimonio_liquido) / 1e9, 1) AS pl_bi, date_format(mode(mes), 'MM/yyyy') AS mes_ref
            FROM {g}.vw_fii_ranking""",
        "rk_cotistas": f"""
            SELECT row_number() OVER (ORDER BY cotistas DESC) AS posicao, ticker, nome_fundo AS fundo, cotistas
            FROM {g}.vw_fii_ranking WHERE cotistas IS NOT NULL ORDER BY cotistas DESC LIMIT 10""",
        "rk_liquidez": f"""
            SELECT row_number() OVER (ORDER BY liquidez_sobre_pl DESC) AS posicao, ticker, nome_fundo AS fundo,
                   round(liquidez_sobre_pl * 100, 2) AS pct
            FROM {g}.vw_fii_ranking WHERE liquidez_sobre_pl IS NOT NULL AND patrimonio_liquido >= 50000000
            ORDER BY liquidez_sobre_pl DESC LIMIT 10""",
        "rk_pl": f"""
            SELECT row_number() OVER (ORDER BY patrimonio_liquido DESC) AS posicao, ticker, nome_fundo AS fundo,
                   round(patrimonio_liquido / 1e9, 2) AS pl_bi
            FROM {g}.vw_fii_ranking WHERE patrimonio_liquido IS NOT NULL ORDER BY patrimonio_liquido DESC LIMIT 10""",
        "rk_dy_mes": f"""
            SELECT row_number() OVER (ORDER BY dy_mes DESC) AS posicao, ticker, nome_fundo AS fundo,
                   round(dy_mes * 100, 2) AS pct
            FROM {g}.vw_fii_ranking WHERE dy_mes > 0 AND dy_mes <= 0.05 AND patrimonio_liquido >= 100000000
            ORDER BY dy_mes DESC LIMIT 10""",
        "rk_dy_12m": f"""
            SELECT row_number() OVER (ORDER BY dy_12m DESC) AS posicao, ticker, nome_fundo AS fundo,
                   round(dy_12m * 100, 2) AS pct
            FROM {g}.vw_fii_ranking WHERE dy_12m > 0 AND dy_12m <= 0.40 AND patrimonio_liquido >= 100000000
            ORDER BY dy_12m DESC LIMIT 10""",
        "rk_rent_12m": f"""
            SELECT row_number() OVER (ORDER BY rentab_12m DESC) AS posicao, ticker, nome_fundo AS fundo,
                   round(rentab_12m * 100, 2) AS pct
            FROM {g}.vw_fii_ranking WHERE rentab_12m BETWEEN -0.9 AND 1.0 AND patrimonio_liquido >= 100000000
            ORDER BY rentab_12m DESC LIMIT 10""",
        "fii_segmentos": f"""
            SELECT segmento, fundos, pl_bi, dy_mediano_mes_pct, fundos_dy_zero, posicoes_cotistas
            FROM {g}.vw_fii_segmentos ORDER BY pl_bi DESC""",
        "lista_fundos": f"""
            SELECT fundo FROM (
              SELECT concat(coalesce(max_by(d.denominacao_social, m.mes), '(sem nome)'), ' · FI · ', m.cnpj_classe) AS fundo,
                     max(m.pl_fim_mes) AS pl
              FROM {g}.fct_fundo_mensal m LEFT JOIN {g}.dim_fundo_classe d USING (cnpj_classe)
              WHERE m.id_subclasse = '' AND m.mes >= add_months({mes_fechado}, -3) GROUP BY m.cnpj_classe
              HAVING pl >= 1000000
              UNION ALL
              SELECT concat(coalesce(max_by(nome_fundo, mes), '(sem nome)'), ' · FII · ', cnpj_classe), max(patrimonio_liquido)
              FROM {g}.fct_fii_mensal WHERE mes >= add_months({mes_fechado}, -9) GROUP BY cnpj_classe
            ) ORDER BY pl DESC""",
        "sel_ficha": f"""
            SELECT * FROM (
              SELECT 'Fundo de investimento (FI)' AS tipo, d.denominacao_social AS nome, m.cnpj_classe AS cnpj,
                     d.administrador, coalesce(d.classificacao, d.tipo_classe) AS classificacao,
                     m.mes AS ultimo_mes, round(m.pl_fim_mes / 1e6, 2) AS pl_mi, m.cotistas_fim_mes AS cotistas
              FROM {g}.fct_fundo_mensal m LEFT JOIN {g}.dim_fundo_classe d USING (cnpj_classe)
              WHERE {TIPO_SEL} = 'FI' AND m.cnpj_classe = {CNPJ_SEL} AND m.id_subclasse = ''
              UNION ALL
              SELECT 'Fundo imobiliário (FII)', nome_fundo, cnpj_classe, nome_administrador, segmento_atuacao, mes,
                     round(patrimonio_liquido / 1e6, 2), cotistas
              FROM {g}.fct_fii_mensal WHERE {TIPO_SEL} = 'FII' AND cnpj_classe = {CNPJ_SEL}
            ) ORDER BY ultimo_mes DESC LIMIT 1""",
        "sel_rentab": f"""
            WITH f AS (
              SELECT mes, rentab_mes * 100 AS valor FROM {g}.fct_fundo_mensal
              WHERE {TIPO_SEL} = 'FI' AND cnpj_classe = {CNPJ_SEL} AND id_subclasse = ''
              UNION ALL
              SELECT mes, rentab_efetiva_mes * 100 FROM {g}.fct_fii_mensal
              WHERE {TIPO_SEL} = 'FII' AND cnpj_classe = {CNPJ_SEL}
            )
            SELECT mes, 'Fundo' AS serie, valor FROM f WHERE mes < {mes_fechado} AND valor IS NOT NULL
            UNION ALL
            SELECT data_referencia, 'Selic do mês', CAST(valor AS DOUBLE) FROM {g}.fct_serie_valor
            WHERE serie_codigo = 4390 AND data_referencia >= (SELECT min(mes) FROM f) AND data_referencia < {mes_fechado}""",
        "sel_pl": f"""
            SELECT mes, round(pl_fim_mes / 1e6, 2) AS pl_mi, cotistas_fim_mes AS cotistas FROM {g}.fct_fundo_mensal
            WHERE {TIPO_SEL} = 'FI' AND cnpj_classe = {CNPJ_SEL} AND id_subclasse = ''
            UNION ALL
            SELECT mes, round(patrimonio_liquido / 1e6, 2), cotistas FROM {g}.fct_fii_mensal
            WHERE {TIPO_SEL} = 'FII' AND cnpj_classe = {CNPJ_SEL}""",
        "sel_dy": f"""
            SELECT mes, round(dividend_yield_mes * 100, 3) AS dy_pct, round(valor_patrimonial_cota, 2) AS cota_patrimonial
            FROM {g}.fct_fii_mensal WHERE {TIPO_SEL} = 'FII' AND cnpj_classe = {CNPJ_SEL}""",
        "sel_cota": f"""
            SELECT dt_comptc AS data, CAST(vl_quota AS DOUBLE) AS cota FROM {g}.fct_fundo_diario
            WHERE {TIPO_SEL} = 'FI' AND cnpj_classe = {CNPJ_SEL} AND id_subclasse = ''""",
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
        # ultima: última execução de reconciliação de cada fonte (todas as entidades/períodos dela).
        # Sem comentários "--" no SQL: as consultas são achatadas numa linha e o comentário engoliria o resto.
        "reconciliacao": f"""
            WITH ultima AS (
              SELECT source_system, max_by(pipeline_run_id, executed_at) AS run FROM {c}.reconciliation_results
              GROUP BY source_system
            )
            SELECT r.source_system AS fonte, r.resultado, count(DISTINCT r.entity_name, r.periodo) AS entidades,
                   sum(r.registos_fonte) AS registos_fonte,
                   sum(r.valores_diferentes + r.so_na_fonte + r.so_na_plataforma) AS divergencias,
                   max(r.executed_at) AS quando
            FROM {c}.reconciliation_results r JOIN ultima u ON u.source_system = r.source_system AND u.run = r.pipeline_run_id
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
           "rentab_mediana_pct": "% no mês", "serie": "Série", "simbolo": "Moeda", "classificacao": "Classificação",
           "pl_mi": "PL (R$ mi)", "cotistas": "Cotistas", "dy_pct": "Dividend yield (% no mês)", "cota": "Cota (R$)",
           "cota_patrimonial": "Cota patrimonial (R$)", "tipo": "Tipo", "nome": "Nome", "cnpj": "CNPJ",
           "administrador": "Administrador", "ultimo_mes": "Último mês", "fonte": "Fonte", "resultado": "Resultado",
           "entidades": "Entidades", "registos_fonte": "Registos na fonte", "divergencias": "Divergências",
           "quando": "Quando", "entidade": "Entidade", "ultima_data": "Última data", "dias": "Dias",
           "reconciliado": "Reconciliado em", "dia": "Dia", "pipeline": "Pipeline", "estado": "Estado",
           "execucoes": "Execuções", "lidos": "Lidos", "escritos": "Escritos", "rejeitados": "Rejeitados",
           "duracao_media_s": "Duração média (s)", "ultima": "Última", "tabela": "Tabela", "regra": "Regra",
           "severidade": "Severidade", "registos_falhados": "Registos", "posicao": "#", "fundo": "Fundo",
           "pl_bi": "PL (R$ bi)", "ticker": "Ticker", "pct": "%", "segmento": "Segmento",
           "dy_mediano_mes_pct": "DY mediano no mês (%)", "fundos_dy_zero": "Informam DY 0",
           "posicoes_cotistas": "Posições de cotistas", "fiis": "FII"}


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
    # formato v2 (o v1 exige dezenas de propriedades por coluna; incompleto dá "Invalid widget definition")
    return widget(nome, ds, cols, {"version": 2, "widgetType": "table", "encodings": {"columns": [
        {"fieldName": c, "displayName": ROTULOS.get(c, c)} for c in cols]},
        "frame": {"showTitle": True, "title": titulo}}, pos)


def filtro_fundo(nome, pos):
    """Dropdown com pesquisa ligado ao parâmetro :fundo de todos os datasets da análise."""
    x, y, w, h = pos
    queries = [{"name": "opcoes", "query": {"datasetName": "lista_fundos", "fields": campos("fundo"),
                                            "disaggregated": False}}]
    queries += [{"name": f"param_{ds}", "query": {"datasetName": ds, "parameters": [{"name": "fundo", "keyword": "fundo"}],
                                                  "disaggregated": False}} for ds in DATASETS_FUNDO]
    campos_ = [{"fieldName": "fundo", "displayName": "Fundo", "queryName": "opcoes"}]
    campos_ += [{"parameterName": "fundo", "queryName": f"param_{ds}"} for ds in DATASETS_FUNDO]
    return {"widget": {"name": nome, "queries": queries, "spec": {
                "version": 2, "widgetType": "filter-single-select", "encodings": {"fields": campos_},
                "frame": {"showTitle": True, "title": "Fundo (escreve parte do nome ou o CNPJ)"}}},
            "position": {"x": x, "y": y, "width": w, "height": h}}


def texto(nome, linhas, pos):
    x, y, w, h = pos
    return {"widget": {"name": nome, "multilineTextboxSpec": {"lines": [linha_ + "\n\n" for linha_ in linhas]}},
            "position": {"x": x, "y": y, "width": w, "height": h}}


def painel(k: str, padrao: str = "") -> dict:
    """padrao: fundo selecionado ao abrir a página de análise."""
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
    fii = [
        texto("t_fii", ["## Fundos imobiliários: rankings", "Fonte: CVM, informe mensal estruturado (último mês de cada "
                        "FII negociado em bolsa, até 4 meses). Ticker derivado do ISIN das cotas. DY e rentabilidade "
                        "são os **informados à CVM** (sobre o património), não sobre a cotação. Rankings de DY e "
                        "rentabilidade só com PL ≥ R$ 100 mi e sem valores extremos (DY no mês > 5 %, DY 12 meses > 40 %, "
                        "rentabilidade 12 meses fora de −90 %…+100 %: costumam ser amortizações ou erros de informe); "
                        "% em caixa = ativos de liquidez / PL (PL ≥ R$ 50 mi). "
                        "Sem cotação do dia, IFIX, liquidez de pregão nem comunicados: são dados da B3, fora das "
                        "fontes oficiais gratuitas usadas."], (0, 0, 6, 2)),
        contador("k_fii_n", "fii_kpi", "fiis", "FII listados com informe", (0, 2, 2, 3)),
        contador("k_fii_seg", "fii_kpi", "segmentos", "Segmentos", (2, 2, 1, 3)),
        contador("k_fii_mes", "fii_kpi", "mes_ref", "Mês de referência", (3, 2, 1, 3)),
        contador("k_fii_pl", "fii_kpi", "pl_bi", "PL somado (R$ bi)", (4, 2, 2, 3)),
        tabela("rk1", "rk_cotistas", ["posicao", "ticker", "fundo", "cotistas"], "Número de cotistas", (0, 5, 2, 8)),
        tabela("rk2", "rk_liquidez", ["posicao", "ticker", "fundo", "pct"], "Percentual em caixa (liquidez / PL)", (2, 5, 2, 8)),
        tabela("rk3", "rk_pl", ["posicao", "ticker", "fundo", "pl_bi"], "Maior património líquido", (4, 5, 2, 8)),
        tabela("rk4", "rk_dy_mes", ["posicao", "ticker", "fundo", "pct"], "Maior DY no último mês (%)", (0, 13, 2, 8)),
        tabela("rk5", "rk_dy_12m", ["posicao", "ticker", "fundo", "pct"], "Maior DY em 12 meses (%)", (2, 13, 2, 8)),
        tabela("rk6", "rk_rent_12m", ["posicao", "ticker", "fundo", "pct"], "Maior rentabilidade em 12 meses (%)", (4, 13, 2, 8)),
        linha("b_seg", "fii_segmentos", "segmento", "pl_bi", None, "PL por segmento (R$ bi)", (0, 21, 3, 7),
              tipo="bar", x_tipo="categorical"),
        tabela("tb_seg", "fii_segmentos", ["segmento", "fundos", "pl_bi", "dy_mediano_mes_pct", "fundos_dy_zero",
                                           "posicoes_cotistas"], "Segmentos", (3, 21, 3, 7)),
    ]
    analise = [
        texto("t_analise", ["## Análise de um fundo", "Escolhe um fundo de investimento (FI, informe diário) ou "
                            "imobiliário (FII, informe mensal). A rentabilidade do FII é a efetiva do mês (inclui "
                            "rendimentos) e compara-se com a Selic acumulada no mês. Meses incompletos ficam de fora."],
              (0, 0, 6, 2)),
        filtro_fundo("f_fundo", (0, 2, 6, 2)),
        tabela("tb_ficha", "sel_ficha", ["tipo", "nome", "cnpj", "administrador", "classificacao", "ultimo_mes",
                                         "pl_mi", "cotistas"], "Ficha", (0, 4, 6, 3)),
        linha("l_sel_rentab", "sel_rentab", "mes", "valor", "serie", "Rentabilidade no mês vs Selic do mês (%)",
              (0, 7, 3, 7)),
        linha("l_sel_pl", "sel_pl", "mes", "pl_mi", None, "Património líquido (R$ mi)", (3, 7, 3, 7)),
        linha("l_sel_cot", "sel_pl", "mes", "cotistas", None, "Cotistas", (0, 14, 3, 6)),
        linha("b_sel_dy", "sel_dy", "mes", "dy_pct", None, "Dividend yield no mês (%), só FII", (3, 14, 3, 6), tipo="bar"),
        linha("l_sel_cota", "sel_cota", "data", "cota", None, "Cota diária (R$), só FI", (0, 20, 6, 6)),
    ]
    ds_ = []
    for n, q in datasets(k).items():
        d = {"name": n, "displayName": n, "queryLines": [" ".join(q.split())]}
        if n in DATASETS_FUNDO:
            d["parameters"] = [{"displayName": "fundo", "keyword": "fundo", "dataType": "STRING",
                                "defaultSelection": {"values": {"dataType": "STRING", "values": [{"value": padrao}]}}}]
        ds_.append(d)
    return {
        "datasets": ds_,
        "pages": [{"name": "mercado", "displayName": "Mercado (BCB)", "layout": mercado},
                  {"name": "fundos", "displayName": "Fundos (CVM)", "layout": fundos},
                  {"name": "fii", "displayName": "FII · rankings", "layout": fii},
                  {"name": "analise", "displayName": "Análise de fundo", "layout": analise},
                  {"name": "operacao", "displayName": "Operação e qualidade", "layout": operacao}],
    }


def fundo_padrao(w: WorkspaceClient, warehouse_id: str, k: str) -> str:
    """Fundo inicial da página de análise: o maior FII do grupo Itaú (administrado pela Intrag ou com Itaú no
    nome), ou o maior FI se não houver FII."""
    from databricks.sdk.service.sql import StatementState

    sql = f"""
        SELECT fundo FROM (
          SELECT concat(max_by(nome_fundo, mes), ' · FII · ', cnpj_classe) AS fundo,
                 max_by(patrimonio_liquido, mes) AS pl, 0 AS ordem
          FROM {k}.gold.fct_fii_mensal
          WHERE upper(nome_administrador) RLIKE 'ITA[UÚ]|INTRAG' OR upper(nome_fundo) RLIKE 'ITA[UÚ]'
          GROUP BY cnpj_classe
          UNION ALL
          SELECT concat(denominacao_social, ' · FI · ', cnpj_classe), vl_patrim_liq, 1 FROM {k}.gold.vw_fundos_maiores_pl
        ) ORDER BY ordem, pl DESC NULLS LAST LIMIT 1"""
    r = w.statement_execution.execute_statement(statement=sql, warehouse_id=warehouse_id, wait_timeout="50s")
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        r = w.statement_execution.get_statement(r.statement_id)
    return r.result.data_array[0][0] if r.result and r.result.data_array else ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="dev")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = carregar_ambiente(args.env)
    w = WorkspaceClient(host=cfg["databricks"]["host"], auth_type="azure-cli")
    wh = next(x for x in w.warehouses.list() if x.name == cfg["databricks"]["sql_warehouse_name"])
    k = cfg["unity_catalog"]["catalog"]
    padrao = fundo_padrao(w, wh.id, k)
    log.info("fundo inicial da análise: %s", padrao)
    conteudo = json.dumps(painel(k, padrao), ensure_ascii=False, indent=1)
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
