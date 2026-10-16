"""Cliente do serviço OData PTAX (Olinda) do Banco Central.

Contrato verificado em 16/10/2026:
- Moedas: value[] com simbolo, nomeFormatado, tipoMoeda.
- CotacaoMoedaPeriodo: value[] com paridadeCompra, paridadeVenda, cotacaoCompra, cotacaoVenda,
  dataHoraCotacao ("aaaa-MM-dd HH:mm:ss.ffffff") e tipoBoletim (Abertura, Intermediário, Fechamento).
- Datas de pedido no formato 'MM-dd-aaaa', entre aspas simples.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterator

from src.common.http import ClienteHttp, ErroFonte

CAMPOS_COTACAO = {"paridadeCompra", "paridadeVenda", "cotacaoCompra", "cotacaoVenda", "dataHoraCotacao", "tipoBoletim"}
CAMPOS_MOEDA = {"simbolo", "nomeFormatado", "tipoMoeda"}


@dataclass
class Pagina:
    entidade: str
    inicio: date | None
    fim: date | None
    url: str
    conteudo: bytes
    registos: list[dict[str, Any]]


def janelas_dias(inicio: date, fim: date, dias: int) -> list[tuple[date, date]]:
    saida, atual = [], inicio
    while atual <= fim:
        b = min(atual + timedelta(days=dias - 1), fim)
        saida.append((atual, b))
        atual = b + timedelta(days=1)
    return saida


def parametros_cotacao(moeda: str, inicio: date, fim: date) -> dict[str, str]:
    return {"@moeda": f"'{moeda}'", "@dataInicial": f"'{inicio:%m-%d-%Y}'",
            "@dataFinalCotacao": f"'{fim:%m-%d-%Y}'", "$format": "json"}


def interpretar(conteudo: bytes, campos: set[str]) -> list[dict[str, Any]]:
    """Devolve os registos com os números no texto original (parse_float=str), sem perda por float."""
    corpo = json.loads(conteudo.decode("utf-8"), parse_float=str, parse_int=str)
    if not isinstance(corpo, dict) or not isinstance(corpo.get("value"), list):
        raise ErroFonte(f"resposta OData sem 'value': {str(corpo)[:300]}")
    for i, r in enumerate(corpo["value"]):
        if set(r) != campos:
            raise ErroFonte(f"registo {i} fora do contrato: campos {sorted(r)} (esperado {sorted(campos)})")
    return corpo["value"]


def extrair_moedas(cliente: ClienteHttp, url: str) -> Pagina:
    r = cliente.get(url, params={"$format": "json"})
    return Pagina("moedas", None, None, r.url, r.conteudo, interpretar(r.conteudo, CAMPOS_MOEDA))


def extrair_cotacoes(cliente: ClienteHttp, url: str, moeda: str, inicio: date, fim: date,
                     janela_dias: int) -> Iterator[Pagina]:
    for a, b in janelas_dias(inicio, fim, janela_dias):
        r = cliente.get(url, params=parametros_cotacao(moeda, a, b))
        yield Pagina(f"cotacao_{moeda}", a, b, r.url, r.conteudo, interpretar(r.conteudo, CAMPOS_COTACAO))
