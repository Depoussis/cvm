"""Deteção de reapresentações (valores revistos pela fonte) a partir do Change Data Feed das tabelas silver SCD1.

O MERGE SCD1 só atualiza quando o record_hash muda, por isso cada par update_preimage/update_postimage no CDF
é uma alteração real de um valor já publicado. O resultado vai para control.reapresentacoes.
"""
from __future__ import annotations

from src.scd.merge_sql import _ident

# tabela silver (sem catálogo) -> (chaves, colunas de negócio)
TABELAS_SCD1 = {
    "silver.bcb_sgs_valores": (["serie_codigo", "data_referencia"], ["valor"]),
    "silver.bcb_ptax_cotacoes": (["moeda", "data_hora_cotacao", "tipo_boletim"],
                                 ["data_cotacao", "paridade_compra", "paridade_venda", "cotacao_compra", "cotacao_venda"]),
    "silver.cvm_fi_informe_diario": (["cnpj_classe", "id_subclasse", "dt_comptc"],
                                     ["tp_fundo_classe", "vl_total", "vl_quota", "vl_patrim_liq", "captc_dia",
                                      "resg_dia", "nr_cotst"]),
}
DIGITOS_VERSAO = 12  # o watermark é texto; versões com zeros à esquerda comparam bem como texto


def versao_texto(v: int) -> str:
    return str(v).zfill(DIGITOS_VERSAO)


def sql_reapresentacoes(tabela: str, chaves: list[str], colunas: list[str], desde: int, ate: int) -> str:
    """SELECT com uma linha por alteração entre as versões [desde, ate] do CDF da tabela."""
    def json_de(alias: str, cols: list[str]) -> str:
        return "to_json(named_struct(" + ", ".join(f"'{c}', {alias}.{_ident(c)}" for c in cols) + "))"

    junta = " AND ".join(f"a.{_ident(k)} <=> d.{_ident(k)}" for k in chaves)
    alteradas = ", ".join(f"IF(a.{_ident(c)} <=> d.{_ident(c)}, NULL, '{c}')" for c in colunas)
    cdf = f"table_changes('{tabela}', {desde}, {ate})"
    return f"""
        SELECT '{tabela}' AS table_name,
               {json_de('d', chaves)} AS chave,
               {json_de('a', colunas)} AS valores_anteriores,
               {json_de('d', colunas)} AS valores_novos,
               filter(array({alteradas}), x -> x IS NOT NULL) AS colunas_alteradas,
               d._commit_version AS commit_version,
               d._commit_timestamp AS commit_timestamp,
               d._pipeline_run_id AS pipeline_run_id,
               current_timestamp() AS detectado_em
        FROM (SELECT * FROM {cdf} WHERE _change_type = 'update_postimage') d
        JOIN (SELECT * FROM {cdf} WHERE _change_type = 'update_preimage') a
          ON {junta} AND a._commit_version = d._commit_version
        WHERE a.record_hash <> d.record_hash"""
