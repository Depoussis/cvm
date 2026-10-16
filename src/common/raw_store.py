"""Guarda os payloads originais no volume raw do Unity Catalog (imutável) e calcula hashes."""
from __future__ import annotations

import hashlib
import os
from datetime import date


def sha256(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def caminho_raw(catalogo: str, fonte: str, entidade: str, data_ingestao: date, run_id: str, ficheiro: str) -> str:
    """/Volumes/<catálogo>/ops/raw/<fonte>/<entidade>/ingestion_date=AAAA-MM-DD/<run_id>/<ficheiro>"""
    for parte in (fonte, entidade, run_id, ficheiro):
        if not parte or "/" in parte or ".." in parte:
            raise ValueError(f"componente de caminho inválido: {parte!r}")
    return (f"/Volumes/{catalogo}/ops/raw/{fonte}/{entidade}/"
            f"ingestion_date={data_ingestao.isoformat()}/{run_id}/{ficheiro}")


def gravar(caminho: str, conteudo: bytes) -> None:
    """Escreve o ficheiro sem nunca sobrescrever um original diferente (a mesma execução pode repetir-se)."""
    if os.path.exists(caminho):
        with open(caminho, "rb") as f:
            if sha256(f.read()) == sha256(conteudo):
                return
        raise FileExistsError(f"já existe um ficheiro diferente em {caminho}")
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "wb") as f:
        f.write(conteudo)
