"""Leitura do snapshot exportado da camada gold (scripts/exportar_painel.py).

Dois sítios possíveis, usa-se o mais recente:
- app/dados/: o snapshot que vem com o repositório (fallback, e o que se usa em desenvolvimento);
- o branch ``painel-dados`` do GitHub, que a Action .github/workflows/exportar_painel.yml substitui a cada
  exportação. A app consulta o ``_meta.json`` remoto de 30 em 30 minutos e, se for mais novo, descarrega o snapshot
  para uma pasta temporária. ``FINDATA_DADOS_URL=""`` desliga a leitura remota.

Colunas de data chegam como ``datetime.date`` e são convertidas para ``datetime64`` aqui, para os gráficos e filtros
não terem de o fazer.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import threading
import urllib.request
from pathlib import Path

import pandas as pd
import streamlit as st

LOCAL = Path(__file__).resolve().parents[1] / "dados"
REMOTO = os.environ.get("FINDATA_DADOS_URL", "https://raw.githubusercontent.com/Depoussis/cvm/painel-dados")
CACHE = Path(tempfile.gettempdir()) / "findata_dados"
COLUNAS_DATA = {"mes", "data", "dia", "ultimo_mes", "data_com"}
log = logging.getLogger(__name__)
_trinco = threading.Lock()


def _exportado_em(pasta: Path) -> str:
    try:
        return json.loads((pasta / "_meta.json").read_text(encoding="utf-8")).get("exportado_em", "")
    except (OSError, ValueError):
        return ""


def _baixar(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 (URL fixa do repositório)
        return r.read()


def _sincronizar() -> Path:
    """Descarrega o snapshot remoto se for mais novo do que o local e devolve a pasta a usar."""
    melhor = max([LOCAL, CACHE], key=_exportado_em)
    if not REMOTO:
        return melhor
    try:
        meta_remoto = json.loads(_baixar(f"{REMOTO}/_meta.json"))
        if meta_remoto.get("exportado_em", "") <= _exportado_em(melhor):
            return melhor
        novo = CACHE.with_name(CACHE.name + ".novo")
        shutil.rmtree(novo, ignore_errors=True)
        novo.mkdir(parents=True)
        for nome in meta_remoto["linhas"]:
            (novo / f"{nome}.parquet").write_bytes(_baixar(f"{REMOTO}/{nome}.parquet"))
        for nome in meta_remoto.get("ficheiros", []):     # outros ficheiros do snapshot (ex.: validacao.json)
            (novo / nome).write_bytes(_baixar(f"{REMOTO}/{nome}"))
        (novo / "_meta.json").write_text(json.dumps(meta_remoto), encoding="utf-8")   # por último: marca completo
        shutil.rmtree(CACHE, ignore_errors=True)
        novo.rename(CACHE)
        log.info("snapshot remoto de %s descarregado", meta_remoto["exportado_em"])
        return CACHE
    except Exception as ex:  # noqa: BLE001 (sem rede ou branch ausente: fica o snapshot local)
        log.warning("snapshot remoto indisponível: %s", ex)
        return melhor


@st.cache_data(ttl=1800, show_spinner=False)
def _pasta_ativa() -> str:
    with _trinco:
        return str(_sincronizar())


def pasta() -> Path:
    return Path(_pasta_ativa())


def _versao(caminho: Path) -> float:
    """Data de modificação do ficheiro: entra na chave da cache para um snapshot novo ser lido sem reiniciar a app."""
    return caminho.stat().st_mtime if caminho.exists() else 0.0


@st.cache_data(show_spinner=False)
def _ler_tabela(caminho: str, versao: float) -> pd.DataFrame:
    df = pd.read_parquet(caminho)
    for c in COLUNAS_DATA & set(df.columns):
        df[c] = pd.to_datetime(df[c])
    return df


def tabela(nome: str) -> pd.DataFrame:
    caminho = pasta() / f"{nome}.parquet"
    return _ler_tabela(str(caminho), _versao(caminho))


@st.cache_data(show_spinner=False)
def _ler_meta(caminho: str, versao: float) -> dict:
    c = Path(caminho)
    return json.loads(c.read_text(encoding="utf-8")) if c.exists() else {}


def meta() -> dict:
    caminho = pasta() / "_meta.json"
    return _ler_meta(str(caminho), _versao(caminho))


def validacao() -> dict:
    """Resultado da validação semanal contra fontes externas (vazio se o snapshot ainda não o tiver)."""
    caminho = pasta() / "validacao.json"
    return _ler_meta(str(caminho), _versao(caminho))


def linha(nome: str) -> pd.Series:
    """Primeira linha de uma tabela de indicadores (kpi_*)."""
    df = tabela(nome)
    return df.iloc[0] if len(df) else pd.Series(dtype=object)


def catalogo_fundos() -> pd.DataFrame:
    return _catalogo_fundos(_versao(pasta() / "_meta.json"))


@st.cache_data(show_spinner=False)
def _catalogo_fundos(versao: float) -> pd.DataFrame:
    """Fundos selecionáveis na análise: FI (informe diário) e FII (informe mensal), com rótulo e PL atual."""
    fi = tabela("fundos_cadastro").assign(tipo="FI", ticker=pd.NA)
    fi = fi[["tipo", "cnpj", "nome", "administrador", "classificacao", "pl_atual", "ticker"]]
    fii_m = tabela("fii_mensal").sort_values("mes")
    fii = fii_m.groupby("cnpj", as_index=False).agg(
        nome=("nome", "last"), administrador=("administrador", "last"), classificacao=("segmento", "last"),
        pl_atual=("pl", "last"), ticker=("ticker", "last"))
    fii["tipo"] = "FII"
    cat = pd.concat([fi, fii[fi.columns]], ignore_index=True)
    cat["nome"] = cat["nome"].fillna("(sem nome)")
    ticker = cat["ticker"].fillna("").astype(str)
    cat["rotulo"] = (ticker.where(ticker == "", ticker + " · ") + cat["nome"] + " · " + cat["tipo"] + " · "
                     + cat["cnpj"].map(formatar_cnpj))
    cat["busca"] = (cat["rotulo"] + " " + cat["cnpj"]).map(_normalizar)
    return cat.sort_values("pl_atual", ascending=False, na_position="last").reset_index(drop=True)


def fundo_padrao(cat: pd.DataFrame) -> int:
    """Índice do fundo aberto por omissão: o maior FII do grupo Itaú (Intrag), como no painel AI/BI."""
    padrao = re.compile(r"ITA[UÚ]|INTRAG")
    alvo = cat[(cat["tipo"] == "FII") & (cat["administrador"].fillna("").str.upper().str.contains(padrao)
                                         | cat["nome"].str.upper().str.contains(padrao))]
    return int(alvo.index[0]) if len(alvo) else 0


def formatar_cnpj(c: str) -> str:
    c = re.sub(r"\D", "", str(c or ""))
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}" if len(c) == 14 else c


def _normalizar(t: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", t.lower())


def buscar(cat: pd.DataFrame, termo: str) -> pd.DataFrame:
    termo = _normalizar(termo).strip()
    if not termo:
        return cat
    digitos = re.sub(r"\D", "", termo)
    mascara = pd.Series(True, index=cat.index)
    for parte in termo.split():
        mascara &= cat["busca"].str.contains(parte, regex=False)
    if len(digitos) >= 6:
        mascara |= cat["cnpj"].str.contains(digitos, regex=False)
    return cat[mascara]
