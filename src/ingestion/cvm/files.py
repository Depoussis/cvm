"""Ficheiros do portal de dados abertos da CVM: lista de meses, contrato de colunas, codificação e ZIP.

Funções puras (sem Spark nem rede), testadas localmente.
"""
from __future__ import annotations

import fnmatch
import io
import posixpath
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from datetime import datetime
from typing import Any

CODIFICACOES = ("UTF-8", "ISO-8859-1")
LIMITE_DESCOMPACTADO = 2 * 1024 ** 3  # proteção contra ZIP malicioso ou corrompido


@dataclass(frozen=True)
class Alvo:
    """Um ficheiro remoto a verificar: URL e período de referência (AAAA-MM, ou None para snapshots)."""
    dataset: str
    url: str
    periodo: str | None


def mes_seguinte(aaaamm: str) -> str:
    a, m = int(aaaamm[:4]), int(aaaamm[5:7])
    return f"{a + (m == 12)}-{1 if m == 12 else m + 1:02d}"


def meses(inicio: str, fim: date) -> list[str]:
    """Meses AAAA-MM de `inicio` até ao mês de `fim`, inclusive."""
    saida, atual, ultimo = [], inicio, f"{fim:%Y-%m}"
    if inicio > ultimo:
        return []
    while atual <= ultimo:
        saida.append(atual)
        atual = mes_seguinte(atual)
    return saida


def meses_a_verificar(run_mode: str, cfg: dict[str, Any], hoje: date, inicio: str | None = None,
                      fim: str | None = None) -> list[str]:
    """backfill: desde inicio_backfill; incremental: últimos `revisao_meses`; reprocess: inicio..fim."""
    primeiro = str(cfg["primeiro_mes_disponivel"])
    if run_mode in {"reprocess", "reconciliation"}:
        if not inicio or not fim:
            raise ValueError(f"run_mode={run_mode} exige data_inicio e data_fim")
        lista = [m for m in meses(inicio, date.fromisoformat(f"{fim}-01")) if m >= primeiro]
    elif run_mode == "backfill":
        lista = meses(max(str(cfg["inicio_backfill"]), primeiro), hoje)
    elif run_mode == "incremental":
        todos = meses(max(str(cfg["inicio_backfill"]), primeiro), hoje)
        lista = todos[-int(cfg["revisao_meses"]):]
    else:
        raise ValueError(f"run_mode inválido: {run_mode!r}")
    return lista


def anos_a_verificar(run_mode: str, cfg: dict[str, Any], hoje: date, inicio: int | None = None,
                     fim: int | None = None) -> list[str]:
    """Conjuntos anuais: backfill desde inicio_backfill; incremental os últimos `revisao_anos`; reprocess inicio..fim."""
    primeiro = int(cfg["primeiro_ano_disponivel"])
    if run_mode in {"reprocess", "reconciliation"}:
        if not inicio or not fim:
            raise ValueError(f"run_mode={run_mode} exige data_inicio e data_fim")
        anos = range(max(inicio, primeiro), fim + 1)
    elif run_mode == "backfill":
        anos = range(max(int(cfg["inicio_backfill"]), primeiro), hoje.year + 1)
    elif run_mode == "incremental":
        anos = range(max(hoje.year - int(cfg["revisao_anos"]) + 1, primeiro), hoje.year + 1)
    else:
        raise ValueError(f"run_mode inválido: {run_mode!r}")
    return [str(a) for a in anos]


def url_ano(modelo: str, aaaa: str) -> str:
    return modelo.format(aaaa=aaaa)


def url_mes(modelo: str, aaaamm: str) -> str:
    return modelo.format(aaaamm=aaaamm.replace("-", ""))


def detectar_codificacao(conteudo: bytes) -> str:
    """UTF-8 se o ficheiro inteiro for UTF-8 válido; senão ISO-8859-1 (que aceita qualquer byte)."""
    try:
        conteudo.decode("utf-8")
        return "UTF-8"
    except UnicodeDecodeError:
        return "ISO-8859-1"


def cabecalho(conteudo: bytes, codificacao: str, separador: str = ";") -> list[str]:
    primeira = conteudo.split(b"\n", 1)[0].decode(codificacao).strip().lstrip("﻿")
    return [c.strip().strip('"') for c in primeira.split(separador)]


def identificar_versao(colunas: list[str], versoes: dict[str, list[str]]) -> str | None:
    """Versão do contrato cujo cabeçalho coincide exatamente (mesmas colunas, mesma ordem)."""
    for nome, esperado in versoes.items():
        if colunas == list(esperado):
            return nome
    return None


def nome_coluna(original: str) -> str:
    """Nome da coluna na bronze: minúsculas, sem acentos, só [a-z0-9_] (ex.: 'Previdência' → 'previdencia')."""
    ascii_ = unicodedata.normalize("NFKD", original).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9_]", "_", ascii_.strip().lower())


def colunas_bronze(versoes: dict[str, list[str]]) -> list[str]:
    """União das colunas de todas as versões (nomes da bronze), pela ordem de primeira aparição."""
    vistas: dict[str, None] = {}
    for esperado in versoes.values():
        for c in esperado:
            vistas.setdefault(nome_coluna(c), None)
    return list(vistas)


def extrair_zip(conteudo: bytes, padrao: str) -> list[tuple[str, bytes]]:
    """Ficheiros do ZIP cujo nome (sem pastas) casa com `padrao`. Rejeita caminhos com '..' ou absolutos."""
    saida = []
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        if sum(i.file_size for i in z.infolist()) > LIMITE_DESCOMPACTADO:
            raise ValueError("ZIP descompactado excede o limite de 2 GB")
        for info in z.infolist():
            nome = info.filename
            if info.is_dir():
                continue
            if nome.startswith("/") or ".." in nome.split("/"):
                raise ValueError(f"caminho inseguro dentro do ZIP: {nome!r}")
            base = posixpath.basename(nome)
            if fnmatch.fnmatch(base, padrao):
                saida.append((base, z.read(info)))
    return saida


def data_http(valor: str | None) -> datetime | None:
    """Converte o cabeçalho Last-Modified para datetime UTC sem fuso (como guardado no Delta)."""
    if not valor:
        return None
    try:
        return parsedate_to_datetime(valor).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def mudou(etag: str | None, last_modified: str | None, anterior: dict[str, Any] | None) -> bool:
    """True quando a fonte indica uma versão diferente da última registada (ou não há registo/ETag)."""
    if not anterior:
        return True
    if etag and anterior.get("source_etag"):
        return etag != anterior["source_etag"]
    novo = data_http(last_modified)
    return novo is None or anterior.get("source_last_modified") is None or novo > anterior["source_last_modified"]
