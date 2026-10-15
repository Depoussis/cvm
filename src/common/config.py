"""Leitura da configuração por ambiente (config/environments/<env>.yaml).

Funciona no PC (repositório local) e no Databricks (repositório em /Workspace/...), porque o caminho
é resolvido a partir deste ficheiro. Variáveis de ambiente FINDATA__<SECCAO>__<CHAVE> sobrepõem valores.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

RAIZ_REPO = Path(__file__).resolve().parents[2]
PASTA_CONFIG = RAIZ_REPO / "config"


def _sobrepor_com_ambiente(cfg: dict[str, Any], prefixo: str = "FINDATA") -> dict[str, Any]:
    for chave, valor in os.environ.items():
        if not chave.startswith(prefixo + "__"):
            continue
        partes = [p.lower() for p in chave.split("__")[1:]]
        alvo = cfg
        for p in partes[:-1]:
            alvo = alvo.setdefault(p, {})
        alvo[partes[-1]] = valor
    return cfg


@lru_cache(maxsize=None)
def carregar_ambiente(env: str) -> dict[str, Any]:
    caminho = PASTA_CONFIG / "environments" / f"{env}.yaml"
    if not caminho.exists():
        raise FileNotFoundError(f"configuração do ambiente '{env}' não encontrada em {caminho}")
    with caminho.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if cfg.get("env") != env:
        raise ValueError(f"{caminho} declara env={cfg.get('env')!r}, esperado {env!r}")
    return _sobrepor_com_ambiente(cfg)


def nome_tabela(cfg: dict[str, Any], schema: str, tabela: str) -> str:
    """Nome totalmente qualificado no Unity Catalog, ex.: findata_dev.control.pipeline_execution."""
    return f"{cfg['unity_catalog']['catalog']}.{schema}.{tabela}"
