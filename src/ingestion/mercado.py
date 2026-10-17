"""Referências de mercado: índices oficiais da B3 e preços/taxas do Tesouro Direto.

Funções puras (sem Spark nem rede), testadas em tests/unit/test_mercado.py. Fontes em config/datasets/mercado.yaml.
"""
from __future__ import annotations

import base64
import csv
import io
import json
from datetime import date
from typing import Any

# ---------------------------------------------------------------- índices B3

CHAVES_INDICE = {"results"}


def url_indice(base: str, indice: str, ano: int) -> str:
    parametros = json.dumps({"index": indice, "language": "pt-br", "year": str(ano)}, separators=(",", ":"))
    return base.format(parametros=base64.b64encode(parametros.encode()).decode())


def linhas_indice(resposta: dict[str, Any], indice: str, ano: int) -> list[dict[str, str]]:
    """Matriz {"results": [{"day": d, "rateValue1".."rateValue12": "128.552,13" | null}]} → uma linha por dia com
    valor (texto, como recebido). Dias sem pregão vêm a null e ficam de fora."""
    if CHAVES_INDICE - set(resposta):
        raise ValueError(f"{indice} {ano}: resposta sem {sorted(CHAVES_INDICE - set(resposta))} (schema drift)")
    linhas = []
    for r in resposta["results"] or []:
        dia = int(r["day"])
        for mes in range(1, 13):
            v = r.get(f"rateValue{mes}")
            if v is not None and str(v).strip():
                linhas.append({"indice": indice, "ano": str(ano), "mes": str(mes), "dia": str(dia), "valor": str(v)})
    return linhas


def anos_a_pedir(run_mode: str, inicio_backfill: int, anos_incremental: int, hoje: date,
                 ultimo_ano_carregado: int | None) -> list[int]:
    """backfill (ou primeira carga): do início configurado até hoje; incremental: os últimos N anos."""
    if run_mode == "backfill" or ultimo_ano_carregado is None:
        return list(range(inicio_backfill, hoje.year + 1))
    return list(range(hoje.year - anos_incremental + 1, hoje.year + 1))


# ---------------------------------------------------------------- Tesouro Direto

COLUNAS_TESOURO = {
    "Tipo Titulo": "tipo_titulo", "Data Vencimento": "data_vencimento", "Data Base": "data_base",
    "Taxa Compra Manha": "taxa_compra", "Taxa Venda Manha": "taxa_venda", "PU Compra Manha": "pu_compra",
    "PU Venda Manha": "pu_venda", "PU Base Manha": "pu_base",
}


def _data(texto: str) -> date | None:
    try:
        d, m, a = (int(x) for x in texto.strip().split("/"))
        return date(a, m, d)
    except (ValueError, AttributeError):
        return None


def linhas_tesouro(conteudo: bytes, desde: date | None = None) -> list[dict[str, str]]:
    """CSV do Tesouro → linhas com as colunas da bronze (texto). ``desde`` filtra pela data base (incremental);
    linhas com data base ilegível passam sempre (a silver põe-nas em quarentena)."""
    texto = conteudo.decode("utf-8-sig", errors="replace") if conteudo[:3] == b"\xef\xbb\xbf" else conteudo.decode("latin-1")
    leitor = csv.DictReader(io.StringIO(texto), delimiter=";")
    em_falta = set(COLUNAS_TESOURO) - set(leitor.fieldnames or [])
    if em_falta:
        raise ValueError(f"CSV do Tesouro sem as colunas {sorted(em_falta)} (schema drift)")
    linhas = []
    for r in leitor:
        if desde is not None:
            d = _data(r["Data Base"])
            if d is not None and d < desde:
                continue
        linhas.append({col: (r[orig].strip() if r[orig] is not None else None) for orig, col in COLUNAS_TESOURO.items()})
    return linhas


def nome_titulo(tipo: str, vencimento: date) -> str:
    """'Tesouro IPCA+' + 2035-05-15 → 'Tesouro IPCA+ 2035' (como aparece no site do Tesouro Direto)."""
    return f"{tipo} {vencimento.year}"
