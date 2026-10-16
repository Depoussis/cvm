"""Leitura do snapshot exportado da camada gold (scripts/exportar_painel.py).

Os ficheiros ficam em app/dados/. Colunas de data chegam como ``datetime.date`` e são convertidas para
``datetime64`` aqui, para os gráficos e filtros não terem de o fazer.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

PASTA = Path(__file__).resolve().parents[1] / "dados"
COLUNAS_DATA = {"mes", "data", "dia", "ultimo_mes", "data_com"}


def _versao(caminho: Path) -> float:
    """Data de modificação do ficheiro: entra na chave da cache para um snapshot novo (git pull no Streamlit Cloud)
    ser lido sem reiniciar a app."""
    return caminho.stat().st_mtime if caminho.exists() else 0.0


@st.cache_data(show_spinner=False)
def _ler_tabela(nome: str, versao: float) -> pd.DataFrame:
    df = pd.read_parquet(PASTA / f"{nome}.parquet")
    for c in COLUNAS_DATA & set(df.columns):
        df[c] = pd.to_datetime(df[c])
    return df


def tabela(nome: str) -> pd.DataFrame:
    return _ler_tabela(nome, _versao(PASTA / f"{nome}.parquet"))


@st.cache_data(show_spinner=False)
def _ler_meta(versao: float) -> dict:
    caminho = PASTA / "_meta.json"
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}


def meta() -> dict:
    return _ler_meta(_versao(PASTA / "_meta.json"))


def linha(nome: str) -> pd.Series:
    """Primeira linha de uma tabela de indicadores (kpi_*)."""
    df = tabela(nome)
    return df.iloc[0] if len(df) else pd.Series(dtype=object)


def catalogo_fundos() -> pd.DataFrame:
    return _catalogo_fundos(_versao(PASTA / "_meta.json"))


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
