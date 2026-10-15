"""Leitura e divisão de ficheiros .sql com variáveis ${nome}, partilhada pelo PC e pelos notebooks."""
from __future__ import annotations

import re
from pathlib import Path

_VAR = re.compile(r"\$\{(\w+)\}")


def renderizar(sql: str, variaveis: dict[str, str]) -> str:
    """Substitui ${nome}; falha se faltar alguma variável (evita criar objetos no catálogo errado)."""
    em_falta = sorted({m.group(1) for m in _VAR.finditer(sql)} - variaveis.keys())
    if em_falta:
        raise KeyError(f"variáveis SQL sem valor: {', '.join(em_falta)}")
    return _VAR.sub(lambda m: variaveis[m.group(1)], sql)


def dividir_instrucoes(sql: str) -> list[str]:
    """Divide por ';' fora de strings e comentários. Suficiente para DDL/DML do projeto (sem blocos BEGIN/END)."""
    instrucoes, atual, i, n = [], [], 0, len(sql)
    em_aspas: str | None = None
    while i < n:
        c = sql[i]
        if em_aspas:
            atual.append(c)
            if c == em_aspas:
                em_aspas = None
        elif c in ("'", '"', "`"):
            em_aspas = c
            atual.append(c)
        elif sql.startswith("--", i):
            fim = sql.find("\n", i)
            i = n if fim == -1 else fim
            continue
        elif c == ";":
            texto = "".join(atual).strip()
            if texto:
                instrucoes.append(texto)
            atual = []
        else:
            atual.append(c)
        i += 1
    resto = "".join(atual).strip()
    if resto:
        instrucoes.append(resto)
    return instrucoes


def carregar_ficheiros(pasta: Path, variaveis: dict[str, str]) -> list[tuple[str, str]]:
    """Devolve (ficheiro, instrução) por ordem alfabética dos ficheiros (01_, 02_, ...)."""
    saida = []
    for f in sorted(pasta.glob("*.sql")):
        for instr in dividir_instrucoes(renderizar(f.read_text(encoding="utf-8"), variaveis)):
            saida.append((f.name, instr))
    return saida
