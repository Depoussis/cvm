"""Exporta da camada gold o snapshot que alimenta o painel Streamlit (app/).

Uso:  python scripts/exportar_painel.py --env dev
Corre as consultas do painel AI/BI (scripts/deploy_dashboard.py) mais o histórico mensal por fundo no SQL Warehouse
e grava app/dados/*.parquet + app/dados/_meta.json. O painel publicado só lê estes ficheiros: não guarda segredos
nem liga o warehouse a cada visita. Depois de exportar, faz commit e push para o Streamlit Cloud republicar.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import requests

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from databricks.sdk import WorkspaceClient  # noqa: E402
from databricks.sdk.service.sql import Disposition, Format, StatementState  # noqa: E402

from scripts.deploy_dashboard import DATASETS_FUNDO, datasets  # noqa: E402
from src.common.config import carregar_ambiente  # noqa: E402

log = logging.getLogger("exportar_painel")
DESTINO = RAIZ / "app" / "dados"
# lista_fundos e sel_* dependem do parâmetro :fundo; no Streamlit o filtro é feito em pandas sobre as tabelas abaixo
IGNORAR = {"lista_fundos", *DATASETS_FUNDO}


def extras(k: str) -> dict[str, str]:
    g = f"{k}.gold"
    mes_fechado = "trunc(current_date(), 'MM')"
    ativos = f"""SELECT cnpj_classe FROM {g}.fct_fundo_mensal
                 WHERE id_subclasse = '' AND mes >= add_months({mes_fechado}, -3)
                 GROUP BY cnpj_classe HAVING max(pl_fim_mes) >= 1000000"""
    return {
        # histórico mensal dos FI com PL >= R$ 1 mi nos últimos 3 meses (o mesmo universo da lista do AI/BI)
        "fundos_mensal": f"""
            SELECT cnpj_classe AS cnpj, mes, rentab_mes, CAST(pl_fim_mes AS DOUBLE) AS pl,
                   cotistas_fim_mes AS cotistas, CAST(captacao_mes - resgate_mes AS DOUBLE) AS captacao_liquida
            FROM {g}.fct_fundo_mensal WHERE id_subclasse = '' AND cnpj_classe IN ({ativos})""",
        "fundos_cadastro": f"""
            SELECT m.cnpj_classe AS cnpj, coalesce(d.denominacao_social, '(sem nome)') AS nome, d.administrador,
                   coalesce(d.classificacao, d.tipo_classe) AS classificacao,
                   CAST(max_by(m.pl_fim_mes, m.mes) AS DOUBLE) AS pl_atual, max(m.mes) AS ultimo_mes
            FROM {g}.fct_fundo_mensal m LEFT JOIN {g}.dim_fundo_classe d USING (cnpj_classe)
            WHERE m.id_subclasse = '' AND m.cnpj_classe IN ({ativos})
            GROUP BY ALL""",
        "fii_mensal": f"""
            SELECT f.cnpj_classe AS cnpj, f.mes, f.nome_fundo AS nome, f.segmento_atuacao AS segmento,
                   f.nome_administrador AS administrador, f.cotistas, CAST(f.patrimonio_liquido AS DOUBLE) AS pl,
                   CAST(f.valor_patrimonial_cota AS DOUBLE) AS cota_patrimonial, f.rentab_efetiva_mes,
                   f.dividend_yield_mes, r.ticker
            FROM {g}.fct_fii_mensal f LEFT JOIN {g}.vw_fii_ranking r USING (cnpj_classe)""",
        "fii_ranking": f"""
            SELECT cnpj_classe AS cnpj, ticker, nome_fundo AS fundo, segmento, nome_administrador AS administrador,
                   mes, CAST(patrimonio_liquido AS DOUBLE) AS pl, cotistas,
                   CAST(liquidez_sobre_pl AS DOUBLE) AS liquidez_sobre_pl, dy_mes, dy_12m, rentab_12m
            FROM {g}.vw_fii_ranking""",
        "selic_mes": f"""SELECT data_referencia AS mes, CAST(valor AS DOUBLE) AS selic_mes_pct
                         FROM {g}.fct_serie_valor WHERE serie_codigo = 4390""",
        # B3: desempenho de todos os papéis com negócios recentes e o histórico diário dos que têm volume médio
        # >= R$ 300 mil/dia (gráfico de evolução e simulador; o fator de evento muda a quantidade de ações)
        "b3_desempenho": f"SELECT * FROM {g}.vw_b3_desempenho",
        "b3_cotacoes": f"""
            SELECT ticker, data_pregao AS data, CAST(preco_fechamento AS DOUBLE) AS fechamento,
                   CAST(preco_ajustado AS FLOAT) AS preco_ajustado, CAST(fator_evento AS FLOAT) AS fator_evento
            FROM {g}.fct_cotacao_diaria
            WHERE ticker IN (SELECT ticker FROM {g}.vw_b3_desempenho WHERE volume_medio_diario >= 300000)""",
        "b3_proventos": f"""
            SELECT ticker, data_com, tipo_provento AS tipo, CAST(valor_por_acao AS DOUBLE) AS valor_por_acao
            FROM {g}.fct_provento
            WHERE data_com >= DATE'2021-01-01'
              AND ticker IN (SELECT ticker FROM {g}.vw_b3_desempenho WHERE volume_medio_diario >= 300000)""",
        # dividendos por ano (ações líquidas) e saídas do modelo de ranking (tabelas pequenas)
        "b3_dividendos": f"""
            SELECT ticker, ano, eventos, valor_ajustado_ano, jcp_ajustado_ano, dy_ano FROM {g}.vw_b3_dividendos_anuais
            WHERE ano >= 2016 AND ticker IN (SELECT ticker FROM {g}.vw_b3_desempenho
                                             WHERE classe_ativo = 'Ação' AND volume_medio_diario >= 1000000)""",
        "ml_resumo": f"SELECT * FROM {g}.ml_resumo",
        "ml_backtest": f"SELECT * FROM {g}.ml_backtest_mensal",
        "ml_importancia": f"SELECT * FROM {g}.ml_importancia",
        "ml_ranking": f"SELECT * FROM {g}.ml_ranking_atual",
    }


def _decimais_para_double(t: pa.Table) -> pa.Table:
    for i, campo in enumerate(t.schema):
        if pa.types.is_decimal(campo.type):
            t = t.set_column(i, campo.name, pc.cast(t.column(i), pa.float64()))
    return t


def consultar(w: WorkspaceClient, warehouse_id: str, sql: str) -> pa.Table:
    r = w.statement_execution.execute_statement(
        statement=sql, warehouse_id=warehouse_id, wait_timeout="50s",
        disposition=Disposition.EXTERNAL_LINKS, format=Format.ARROW_STREAM)
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"consulta falhou: {r.status.error}")
    partes = []
    chunk = r.result
    while chunk is not None:
        for link in chunk.external_links or []:
            # o link é um SAS temporário do armazenamento: não leva o token do Databricks
            corpo = requests.get(link.external_link, timeout=120)
            corpo.raise_for_status()
            partes.append(pa.ipc.open_stream(corpo.content).read_all())
        prox = chunk.next_chunk_index
        chunk = w.statement_execution.get_statement_result_chunk_n(r.statement_id, prox) if prox is not None else None
    if not partes:  # resultado vazio: monta a tabela a partir do esquema
        nomes = [c.name for c in r.manifest.schema.columns]
        return pa.table({n: pa.array([], pa.string()) for n in nomes})
    return _decimais_para_double(pa.concat_tables(partes))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="dev")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = carregar_ambiente(args.env)
    w = WorkspaceClient(host=cfg["databricks"]["host"], auth_type="azure-cli")
    wh = next(x for x in w.warehouses.list() if x.name == cfg["databricks"]["sql_warehouse_name"])
    k = cfg["unity_catalog"]["catalog"]

    consultas = {n: q for n, q in datasets(k).items() if n not in IGNORAR} | extras(k)
    DESTINO.mkdir(parents=True, exist_ok=True)
    linhas = {}
    for nome, sql in consultas.items():
        t = consultar(w, wh.id, " ".join(sql.split()))
        pq.write_table(t, DESTINO / f"{nome}.parquet", compression="zstd")
        linhas[nome] = t.num_rows
        log.info("%-16s %8d linhas", nome, t.num_rows)
    meta = {"exportado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ambiente": args.env,
            "catalogo": k, "linhas": linhas}
    (DESTINO / "_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(p.stat().st_size for p in DESTINO.glob("*.parquet")) / 1e6
    log.info("snapshot em %s (%.1f MB)", DESTINO, total)


if __name__ == "__main__":
    main()
