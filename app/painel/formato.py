"""Formatação de números e datas no padrão português/brasileiro (milhar com ponto, decimal com vírgula)."""
from __future__ import annotations

import math

import pandas as pd

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _vazio(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA or v is pd.NaT


def numero(v, casas: int = 0) -> str:
    if _vazio(v):
        return "—"
    texto = f"{float(v):,.{casas}f}"
    return texto.replace(",", "§").replace(".", ",").replace("§", ".")


def pct(v, casas: int = 2, sinal: bool = False) -> str:
    """``v`` já em pontos percentuais (1.5 -> '1,50 %')."""
    if _vazio(v):
        return "—"
    s = numero(v, casas)
    if sinal and float(v) > 0:
        s = "+" + s
    return f"{s} %"


def brl(v, casas: int = 2) -> str:
    return "—" if _vazio(v) else f"R$ {numero(v, casas)}"


def compacto(v) -> str:
    """Valores em reais abreviados: R$ 1,2 tri / R$ 3,4 bi / R$ 56,7 mi / R$ 890 mil."""
    if _vazio(v):
        return "—"
    v = float(v)
    for limite, sufixo in ((1e12, "tri"), (1e9, "bi"), (1e6, "mi"), (1e3, "mil")):
        if abs(v) >= limite:
            return f"R$ {numero(v / limite, 1)} {sufixo}"
    return brl(v, 0)


def mes(d) -> str:
    """'ago/2026'."""
    if _vazio(d):
        return "—"
    d = pd.Timestamp(d)
    return f"{MESES[d.month - 1]}/{d.year}"


def data(d) -> str:
    return "—" if _vazio(d) else pd.Timestamp(d).strftime("%d/%m/%Y")


def data_hora(d) -> str:
    if _vazio(d):
        return "—"
    t = pd.Timestamp(d)
    if t.tzinfo is not None:
        t = t.tz_convert("America/Sao_Paulo")
    return t.strftime("%d/%m/%Y %H:%M")
