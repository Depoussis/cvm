"""Séries históricas de cotações da B3 (COTAHIST): layout de largura fixa, URLs e validação do ficheiro.

Funções puras (sem Spark nem rede), testadas localmente. Layout oficial: "Cotações Históricas - Layout do arquivo"
(B3, SerHist/SeriesHistoricas_Layout.pdf). Cada linha tem 245 posições:
- registo 00: cabeçalho (nome do ficheiro, origem, data de geração);
- registo 01: uma cotação (papel, mercado, preços, negócios, volume);
- registo 99: trailer com o número de registos (observado: só as cotações, sem cabeçalho e trailer).
"""
from __future__ import annotations

import io
import shutil
import zipfile
from datetime import date, timedelta
from typing import Any, BinaryIO

TAMANHO_LINHA = 245
LIMITE_DESCOMPACTADO = 4 * 1024 ** 3   # o anual descompactado tem ~1,1 GB

# (campo na bronze, posição inicial, posição final), posições 1-based e inclusivas, como no layout da B3
LAYOUT: list[tuple[str, int, int]] = [
    ("tipreg", 1, 2), ("data_pregao", 3, 10), ("codbdi", 11, 12), ("codneg", 13, 24), ("tpmerc", 25, 27),
    ("nomres", 28, 39), ("especi", 40, 49), ("prazot", 50, 52), ("modref", 53, 56), ("preabe", 57, 69),
    ("premax", 70, 82), ("premin", 83, 95), ("premed", 96, 108), ("preult", 109, 121), ("preofc", 122, 134),
    ("preofv", 135, 147), ("totneg", 148, 152), ("quatot", 153, 170), ("voltot", 171, 188), ("preexe", 189, 201),
    ("indopc", 202, 202), ("datven", 203, 210), ("fatcot", 211, 217), ("ptoexe", 218, 230), ("codisi", 231, 242),
    ("dismes", 243, 245),
]
COLUNAS = [c for c, _, _ in LAYOUT]
# preços e volume vêm com 2 casas decimais implícitas (ex.: 0000000005760 = 57,60)
COM_2_CASAS = {"preabe", "premax", "premin", "premed", "preult", "preofc", "preofv", "voltot", "preexe"}


def parse_linha(linha: str) -> dict[str, str]:
    """Campos de um registo, como texto sem espaços à direita (o que fica na bronze)."""
    return {c: linha[i - 1:f].rstrip() for c, i, f in LAYOUT}


def valor(campo: str, texto: str) -> float | int | None:
    """Converte um campo numérico do layout (com as casas implícitas). Vazio → None."""
    t = texto.strip()
    if not t:
        return None
    return int(t) / 100 if campo in COM_2_CASAS else int(t)


def expressoes_spark(coluna: str = "linha") -> list[str]:
    """SELECT de cada campo a partir da linha completa (substring é 1-based no Spark SQL)."""
    return [f"rtrim(substring({coluna}, {i}, {f - i + 1})) AS {c}" for c, i, f in LAYOUT]


def url_ano(modelo: str, ano: int | str) -> str:
    return modelo.format(aaaa=ano)


def url_dia(modelo: str, dia: date) -> str:
    return modelo.format(ddmmaaaa=f"{dia:%d%m%Y}")


def dias_uteis(inicio: date, fim: date) -> list[date]:
    """Segunda a sexta entre as datas (feriados respondem 404 e são ignorados pelo notebook)."""
    return [inicio + timedelta(d) for d in range((fim - inicio).days + 1) if (inicio + timedelta(d)).weekday() < 5]


def alvos(run_mode: str, cfg: dict[str, Any], hoje: date, inicio: date | None = None,
          fim: date | None = None) -> list[tuple[str, str]]:
    """(url, período) a verificar.

    backfill: ficheiros anuais desde `inicio_backfill` até ao ano corrente (o anual do ano corrente vai até ao último
    pregão); incremental: ficheiros diários dos últimos `revisao_dias` dias úteis; reprocess/reconciliation: anuais
    dos anos entre data_inicio e data_fim.
    """
    if run_mode == "backfill":
        anos = range(max(int(cfg["inicio_backfill"]), int(cfg["primeiro_ano_disponivel"])), hoje.year + 1)
        return [(url_ano(cfg["url_anual"], a), str(a)) for a in anos]
    if run_mode == "incremental":
        dias = dias_uteis(hoje - timedelta(days=int(cfg["revisao_dias"])), hoje)
        return [(url_dia(cfg["url_diario"], d), d.isoformat()) for d in dias]
    if run_mode in {"reprocess", "reconciliation"}:
        if not inicio or not fim:
            raise ValueError(f"run_mode={run_mode} exige data_inicio e data_fim")
        return [(url_ano(cfg["url_anual"], a), str(a)) for a in range(inicio.year, fim.year + 1)]
    raise ValueError(f"run_mode inválido: {run_mode!r}")


def extrair_txt(conteudo: bytes, destino: BinaryIO) -> str:
    """Copia o único .TXT do ZIP para `destino` em blocos (o anual tem ~1,1 GB). Devolve o nome do ficheiro."""
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        membros = [i for i in z.infolist() if not i.is_dir()]
        if len(membros) != 1 or not membros[0].filename.upper().endswith(".TXT"):
            raise ValueError(f"esperado um único .TXT no ZIP, encontrado: {[m.filename for m in membros]}")
        info = membros[0]
        if info.file_size > LIMITE_DESCOMPACTADO:
            raise ValueError("ZIP descompactado excede o limite de 4 GB")
        if info.filename.startswith("/") or ".." in info.filename.replace("\\", "/").split("/"):
            raise ValueError(f"caminho inseguro dentro do ZIP: {info.filename!r}")
        with z.open(info) as origem:
            shutil.copyfileobj(origem, destino, 16 * 1024 ** 2)
        return info.filename.replace("\\", "/").rsplit("/", 1)[-1]


def validar_envelope(cabecalho: str, trailer: str, detalhes: int) -> list[str]:
    """Problemas no cabeçalho/trailer (lista vazia = ficheiro completo).

    O trailer (registo 99) traz, nas posições 32-42, o total de registos. O layout diz que inclui cabeçalho e trailer,
    mas no diário de 15/10/2026 o total era só o das cotações; aceitam-se as duas leituras.
    """
    problemas = []
    if not cabecalho.startswith("00COTAHIST"):
        problemas.append(f"cabeçalho inesperado: {cabecalho[:40]!r}")
    if not trailer.startswith("99COTAHIST"):
        problemas.append(f"trailer inesperado: {trailer[:40]!r}")
        return problemas
    total = trailer[31:42].strip()
    if not total.isdigit():
        problemas.append(f"total de registos ilegível no trailer: {total!r}")
    elif int(total) not in (detalhes, detalhes + 2):
        problemas.append(f"trailer indica {int(total)} registos, o ficheiro tem {detalhes} cotações")
    return problemas
