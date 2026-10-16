"""Cálculo do intervalo de datas pedido à fonte em cada modo de execução."""
from __future__ import annotations

from datetime import date, timedelta


def intervalo(run_mode: str, inicio_backfill: date, revisao_dias: int, hoje: date,
              watermark: date | None = None, inicio: date | None = None, fim: date | None = None) -> tuple[date, date]:
    """
    - backfill: do início configurado até hoje.
    - incremental: do watermark menos a janela de revisão até hoje (revisões da fonte são recarregadas);
      sem watermark, comporta-se como backfill.
    - reprocess / reconciliation: intervalo explícito (inicio e fim obrigatórios).
    """
    if run_mode in {"reprocess", "reconciliation"}:
        if not inicio or not fim:
            raise ValueError(f"run_mode={run_mode} exige data_inicio e data_fim")
        a, b = inicio, fim
    elif run_mode == "backfill":
        a, b = inicio or inicio_backfill, fim or hoje
    elif run_mode == "incremental":
        if watermark is None:
            a = inicio_backfill
        else:
            a = max(inicio_backfill, min(watermark, hoje) - timedelta(days=revisao_dias))
        b = hoje
    else:
        raise ValueError(f"run_mode inválido: {run_mode!r}")
    if b < a:
        raise ValueError(f"intervalo vazio: {a} > {b}")
    return a, b
