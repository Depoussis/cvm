"""Geração das instruções MERGE de SCD1 e SCD2 (Delta). Funções puras, testadas sem Spark.

Convenções das tabelas silver:
- `record_hash`: sha256 das colunas de negócio; só há escrita quando muda.
- SCD1: `_inserted_at`, `_updated_at`, `_pipeline_run_id`.
- SCD2: `valid_from`, `valid_to` (NULL na versão atual), `is_current`, `_pipeline_run_id`.
"""
from __future__ import annotations


def _ident(nome: str) -> str:
    if not nome.replace("_", "").isalnum():
        raise ValueError(f"identificador inválido: {nome!r}")
    return f"`{nome}`"


def expr_hash(colunas: list[str]) -> str:
    """sha256 das colunas como texto; NULL vira um marcador para não colidir com string vazia."""
    partes = ", ".join(f"coalesce(cast({_ident(c)} as string), '\\u2205')" for c in colunas)
    return f"sha2(concat_ws('||', {partes}), 256)"


def merge_scd1(destino: str, origem: str, chaves: list[str], colunas: list[str]) -> str:
    on = " AND ".join(f"t.{_ident(k)} <=> s.{_ident(k)}" for k in chaves)
    todas = chaves + colunas + ["record_hash"]
    upd = ", ".join(f"t.{_ident(c)} = s.{_ident(c)}" for c in colunas + ["record_hash"])
    ins_c = ", ".join(_ident(c) for c in todas + ["_inserted_at", "_updated_at", "_pipeline_run_id"])
    ins_v = ", ".join([f"s.{_ident(c)}" for c in todas] + ["current_timestamp()", "current_timestamp()", "s._pipeline_run_id"])
    return (f"MERGE INTO {destino} t USING {origem} s ON {on}\n"
            f"WHEN MATCHED AND t.record_hash <> s.record_hash THEN UPDATE SET {upd}, "
            f"t._updated_at = current_timestamp(), t._pipeline_run_id = s._pipeline_run_id\n"
            f"WHEN NOT MATCHED THEN INSERT ({ins_c}) VALUES ({ins_v})")


def merge_scd2(destino: str, origem: str, chaves: list[str], colunas: list[str]) -> str:
    """Fecha a versão atual quando o hash muda e insere a nova. Chaves novas entram como versão atual.

    Técnica: a origem é duplicada para as chaves alteradas; a cópia com `_mk_*` NULL nunca casa e vira INSERT.
    """
    mk = [f"_mk_{k}" for k in chaves]
    sel_chaves = ", ".join(f"s.{_ident(k)} AS {_ident(m)}" for k, m in zip(chaves, mk))
    sel_nulos = ", ".join(f"NULL AS {_ident(m)}" for m in mk)  # tipo herdado do primeiro ramo do UNION
    junta = " AND ".join(f"a.{_ident(k)} <=> s.{_ident(k)}" for k in chaves)
    on = " AND ".join(f"t.{_ident(k)} <=> u.{_ident(m)}" for k, m in zip(chaves, mk))
    todas = chaves + colunas + ["record_hash"]
    ins_c = ", ".join(_ident(c) for c in todas + ["valid_from", "valid_to", "is_current", "_pipeline_run_id"])
    ins_v = ", ".join([f"u.{_ident(c)}" for c in todas] + ["current_timestamp()", "NULL", "true", "u._pipeline_run_id"])
    return (f"MERGE INTO {destino} t USING (\n"
            f"  SELECT s.*, {sel_chaves} FROM {origem} s\n"
            f"  UNION ALL\n"
            f"  SELECT s.*, {sel_nulos} FROM {origem} s JOIN {destino} a ON {junta}\n"
            f"   WHERE a.is_current AND a.record_hash <> s.record_hash\n"
            f") u ON {on} AND t.is_current\n"
            f"WHEN MATCHED AND t.record_hash <> u.record_hash THEN UPDATE SET "
            f"t.is_current = false, t.valid_to = current_timestamp()\n"
            f"WHEN NOT MATCHED THEN INSERT ({ins_c}) VALUES ({ins_v})")


def fechar_ausentes_scd2(destino: str, origem: str, chaves: list[str]) -> str:
    """Para fontes em snapshot completo: fecha as versões atuais cujas chaves já não aparecem na origem."""
    sel = ", ".join(f"a.{_ident(k)}" for k in chaves)
    anti = " AND ".join(f"a.{_ident(k)} <=> s.{_ident(k)}" for k in chaves)
    on = " AND ".join(f"t.{_ident(k)} <=> x.{_ident(k)}" for k in chaves)
    return (f"MERGE INTO {destino} t USING (\n"
            f"  SELECT {sel} FROM {destino} a LEFT ANTI JOIN {origem} s ON {anti} WHERE a.is_current\n"
            f") x ON {on} AND t.is_current\n"
            f"WHEN MATCHED THEN UPDATE SET t.is_current = false, t.valid_to = current_timestamp()")
