"""Cliente da API SGS do Banco Central (séries temporais). Funções puras + um extrator que usa ClienteHttp.

Comportamento real da API (verificado em 16/10/2026):
- 200 com lista [{"data": "dd/MM/aaaa", "valor": "1.23"}]; a ordem nem sempre é crescente.
- 404 com {"erro": {... "Value(s) not found"}} quando a janela não tem valores.
- 406 quando a janela de uma série diária passa de 10 anos.
- Séries mensais devolvem o mês que contém dataInicial, mesmo que a data pedida seja posterior ao dia 1.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator

from src.common.http import ClienteHttp, ErroFonte

SEM_DADOS = "Value(s) not found"


@dataclass(frozen=True)
class Serie:
    codigo: int
    nome: str
    periodicidade: str
    inicio_backfill: date
    permite_futuro: bool
    revisao_dias: int

    @property
    def entidade(self) -> str:
        return f"serie_{self.codigo}"

    @classmethod
    def de_config(cls, d: dict[str, Any]) -> "Serie":
        if d["periodicidade"] not in {"diaria", "mensal"}:
            raise ValueError(f"periodicidade desconhecida na série {d['codigo']}: {d['periodicidade']}")
        inicio = d["inicio_backfill"]
        return cls(int(d["codigo"]), d["nome"], d["periodicidade"],
                   inicio if isinstance(inicio, date) else date.fromisoformat(str(inicio)),
                   bool(d["permite_futuro"]), int(d["revisao_dias"]))


@dataclass
class Pagina:
    """Resposta de uma janela: o payload original (para o raw) e os registos interpretados."""
    serie: Serie
    inicio: date
    fim: date
    url: str
    status: int
    conteudo: bytes
    registos: list[dict[str, str]]


def janelas(inicio: date, fim: date, anos: int) -> list[tuple[date, date]]:
    """Divide [inicio, fim] em janelas consecutivas de no máximo `anos` anos (limite da API: 10)."""
    if fim < inicio:
        return []
    saida, atual = [], inicio
    while atual <= fim:
        try:
            limite = atual.replace(year=atual.year + anos) - timedelta(days=1)
        except ValueError:  # 29/02 sem ano bissexto destino
            limite = atual.replace(year=atual.year + anos, day=28)
        saida.append((atual, min(limite, fim)))
        atual = min(limite, fim) + timedelta(days=1)
    return saida


def parametros(inicio: date, fim: date) -> dict[str, str]:
    return {"formato": "json", "dataInicial": inicio.strftime("%d/%m/%Y"), "dataFinal": fim.strftime("%d/%m/%Y")}


def interpretar(status: int, conteudo: bytes) -> list[dict[str, str]]:
    """Valida o contrato da resposta e devolve os registos como texto, sem conversões (a bronze guarda o original)."""
    corpo = json.loads(conteudo.decode("utf-8"))
    if status == 404:
        detalhe = json.dumps(corpo, ensure_ascii=False)
        if SEM_DADOS in detalhe:
            return []
        raise ErroFonte(f"404 inesperado do SGS: {detalhe[:300]}")
    if not isinstance(corpo, list):
        raise ErroFonte(f"resposta do SGS não é uma lista: {str(corpo)[:300]}")
    for i, r in enumerate(corpo):
        if not isinstance(r, dict) or set(r) != {"data", "valor"}:
            raise ErroFonte(f"registo {i} fora do contrato (esperado data/valor): {str(r)[:200]}")
    return corpo


def converter_data(texto: str) -> date:
    return datetime.strptime(texto, "%d/%m/%Y").date()


def converter_valor(texto: str) -> Decimal:
    try:
        return Decimal(texto)
    except InvalidOperation as e:
        raise ValueError(f"valor não numérico: {texto!r}") from e


def extrair(cliente: ClienteHttp, url_modelo: str, serie: Serie, inicio: date, fim: date,
            janela_anos: int) -> Iterator[Pagina]:
    url = url_modelo.format(codigo=serie.codigo)
    for a, b in janelas(inicio, fim, janela_anos):
        r = cliente.get(url, params=parametros(a, b), aceitar=frozenset({404}))
        yield Pagina(serie, a, b, r.url, r.status, r.conteudo, interpretar(r.status, r.conteudo))
