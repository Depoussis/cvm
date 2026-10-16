# Databricks notebook source
# MAGIC %md
# MAGIC # Silver · CVM
# MAGIC - `cvm_fi_informe_diario` (SCD1): harmoniza as duas versões do cabeçalho (antes/depois da RCVM 175), normaliza o
# MAGIC   CNPJ, converte para os tipos do dicionário da CVM e rejeita para quarentena o que não converte sem perda.
# MAGIC - `cvm_fundo`, `cvm_fundo_gestor`, `cvm_fundo_classe`, `cvm_companhia` (SCD2): a partir do snapshot mais recente
# MAGIC   ainda não consolidado. Chaves que desaparecem do snapshot têm a versão atual fechada.
# MAGIC - Dados pessoais da bronze não são selecionados.

# COMMAND ----------

import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd().parents[1]))

from src.common import notebook

notebook.declarar(dbutils)
p = notebook.ler(dbutils)
print(p)

# COMMAND ----------

from datetime import date

from src.audit import control
from src.quality import rules as dq
from src.scd.merge_sql import expr_hash, fechar_ausentes_scd2, merge_scd1, merge_scd2
from src.silver.common import caminho_quarentena, executar_merge, sql_pendentes

FONTE = "cvm"
k = p.catalogo
hoje = date.today()
reprocessar = p.run_mode == "reprocess"
erros = {}


def txt(c: str) -> str:
    return f"nullif(trim({c}), '')"


def dt(c: str) -> str:
    return f"try_to_date(nullif(trim({c}), ''), 'yyyy-MM-dd')"


def cnpj(c: str) -> str:
    return f"nullif(regexp_replace({c}, '[^0-9]', ''), '')"


def num_ok(c: str, inteiros: int, decimais: int) -> str:
    """Texto vazio (NULL) ou número que cabe em DECIMAL(inteiros+decimais, decimais) sem arredondar."""
    frac = f"([.][0-9]{{1,{decimais}}})?" if decimais else ""  # [.] evita escapes dentro do literal SQL
    return f"(nullif(trim({c}), '') IS NULL OR trim({c}) rlike '^-?[0-9]{{1,{inteiros}}}{frac}$')"


# COMMAND ----------

# MAGIC %md ## Informe diário (SCD1)

# COMMAND ----------

if p.escolhida("fi_inf_diario"):
    bronze = f"{k}.bronze.cvm_fi_inf_diario"
    destino = f"{k}.silver.cvm_fi_informe_diario"
    e = control.Execucao(k, p.run_id, "silver_cvm", FONTE, "fi_inf_diario", "silver", p.run_mode)
    control.iniciar(spark, e)
    c = control.Contagens()
    try:
        src_sql = sql_pendentes(bronze, k, FONTE, "fi_inf_diario", "true", reprocessar)
        valido = " AND ".join([
            "_corrupt_record IS NULL",
            f"length({cnpj('coalesce(cnpj_fundo_classe, cnpj_fundo)')}) = 14",
            f"{dt('dt_comptc')} IS NOT NULL",
            num_ok("vl_total", 15, 2), num_ok("vl_quota", 15, 12), num_ok("vl_patrim_liq", 15, 2),
            num_ok("captc_dia", 15, 2), num_ok("resg_dia", 15, 2), num_ok("nr_cotst", 9, 0),
        ])
        spark.sql(f"SELECT *, coalesce(({valido}), false) AS _valido FROM ({src_sql})").createOrReplaceTempView("_inf_pend")
        c.read = spark.table("_inf_pend").count()
        invalidos = spark.table("_inf_pend").where("NOT _valido").drop("_valido")
        c.rejected = invalidos.count()
        if c.rejected:
            invalidos.write.mode("append").json(caminho_quarentena(k, FONTE, "fi_inf_diario", hoje, p.run_id))
        colunas = ["tp_fundo_classe", "vl_total", "vl_quota", "vl_patrim_liq", "captc_dia", "resg_dia", "nr_cotst"]
        spark.sql(f"""
            SELECT cnpj_classe, id_subclasse, dt_comptc, {', '.join(colunas)},
                   {expr_hash(colunas)} AS record_hash, '{p.run_id}' AS _pipeline_run_id
            FROM (
              SELECT {cnpj('coalesce(cnpj_fundo_classe, cnpj_fundo)')} AS cnpj_classe,
                     coalesce({txt('id_subclasse')}, '') AS id_subclasse,
                     {dt('dt_comptc')} AS dt_comptc,
                     coalesce({txt('tp_fundo_classe')}, {txt('tp_fundo')}) AS tp_fundo_classe,
                     CAST({txt('vl_total')} AS DECIMAL(17,2)) AS vl_total,
                     CAST({txt('vl_quota')} AS DECIMAL(27,12)) AS vl_quota,
                     CAST({txt('vl_patrim_liq')} AS DECIMAL(17,2)) AS vl_patrim_liq,
                     CAST({txt('captc_dia')} AS DECIMAL(17,2)) AS captc_dia,
                     CAST({txt('resg_dia')} AS DECIMAL(17,2)) AS resg_dia,
                     CAST({txt('nr_cotst')} AS INT) AS nr_cotst,
                     _ingestion_timestamp, _record_hash
              FROM _inf_pend WHERE _valido
            )
            -- Na transição para a RCVM 175 a CVM publicou o mesmo fundo/dia duas vezes, como 'FI' e como
            -- 'CLASSES - FIF', com os mesmos valores (~39 mil casos em 2024-2026). Fica a versão mais recente
            -- e, no mesmo ficheiro, a do tipo novo (CLASSE...).
            QUALIFY row_number() OVER (PARTITION BY cnpj_classe, id_subclasse, dt_comptc
                                       ORDER BY _ingestion_timestamp DESC,
                                                CASE WHEN tp_fundo_classe LIKE 'CLASSE%' THEN 0 ELSE 1 END,
                                                _record_hash) = 1
        """).createOrReplaceTempView("_inf_src")
        n_validos = spark.table("_inf_src").count()
        c.inserted, c.updated = executar_merge(spark, merge_scd1(
            destino, "_inf_src", ["cnpj_classe", "id_subclasse", "dt_comptc"], colunas))
        c.unchanged = n_validos - c.inserted - c.updated

        da_execucao = f"SELECT * FROM {destino} WHERE _pipeline_run_id = '{p.run_id}'"
        sql_dup = (f"SELECT {cnpj('coalesce(cnpj_fundo_classe, cnpj_fundo)')} AS cnpj_classe, "
                   f"coalesce({txt('id_subclasse')}, '') AS id_subclasse, dt_comptc, _file_hash, "
                   f"collect_set(coalesce(tp_fundo_classe, tp_fundo)) AS tipos, count(*) AS n, "
                   f"count(DISTINCT vl_total, vl_quota, vl_patrim_liq, captc_dia, resg_dia, nr_cotst) AS versoes "
                   f"FROM _inf_pend WHERE _valido GROUP BY 1, 2, 3, 4 HAVING n > 1")
        total_exec = f"SELECT count(*) FROM ({da_execucao})"
        regras = [
            dq.Regra("chave_unica", "Uma linha por (CNPJ, subclasse, data)", "CRITICAL", destino,
                     f"SELECT cnpj_classe, id_subclasse, dt_comptc, count(*) n FROM {destino} "
                     f"GROUP BY ALL HAVING n > 1", f"SELECT count(*) FROM {destino}"),
            dq.Regra("formato_api", "CNPJ, data e números convertíveis sem perda; linha com o número certo de campos",
                     "HIGH", bronze, "SELECT * FROM _inf_pend WHERE NOT _valido", "SELECT count(*) FROM _inf_pend"),
            dq.Regra("data_nao_futura", "Data de competência não posterior a hoje", "HIGH", destino,
                     f"SELECT * FROM ({da_execucao}) WHERE dt_comptc > current_date()", total_exec),
            # Mesmo (CNPJ, subclasse, data) repetido no mesmo ficheiro (FI e CLASSES - FIF na transição RCVM 175).
            # Fica a linha do regime novo (ver QUALIFY acima); separa-se o caso em que os valores também diferem,
            # porque aí a escolha é um pressuposto da plataforma e não uma regra da CVM.
            dq.Regra("duplicado_na_fonte_valores_iguais", "Chave repetida no ficheiro com os mesmos valores", "INFO",
                     bronze, f"{sql_dup} AND versoes = 1", "SELECT count(*) FROM _inf_pend"),
            dq.Regra("duplicado_na_fonte_valores_diferentes",
                     "Chave repetida no ficheiro com valores diferentes; mantida a linha CLASSE* (pressuposto)", "INFO",
                     bronze, f"{sql_dup} AND versoes > 1", "SELECT count(*) FROM _inf_pend"),
            # Plausibilidade: só regista (a CVM publica o que os administradores enviam)
            dq.Regra("cota_positiva", "Valor da cota maior que zero", "INFO", destino,
                     f"SELECT cnpj_classe, id_subclasse, dt_comptc, vl_quota FROM ({da_execucao}) WHERE vl_quota <= 0",
                     total_exec),
            dq.Regra("cotistas_nao_negativos", "Número de cotistas não negativo", "INFO", destino,
                     f"SELECT cnpj_classe, dt_comptc, nr_cotst FROM ({da_execucao}) WHERE nr_cotst < 0", total_exec),
        ]
        resultados = dq.avaliar(spark, regras)
        dq.gravar(spark, k, p.run_id, resultados)
        criticas = [r.regra.nome for r in resultados if not r.passou and r.regra.severidade == "CRITICAL"]
        maximo = spark.sql(f"SELECT max(dt_comptc) FROM {destino}").first()[0]
        if maximo and not criticas:
            control.confirmar_watermark(spark, e, "reference_date", maximo.isoformat(), None)
        control.concluir(spark, e, c)
        print(f"fi_inf_diario: lidos={c.read} novos={c.inserted} alterados={c.updated} iguais={c.unchanged} "
              f"rejeitados={c.rejected} watermark={maximo} falhas={[r.regra.nome for r in resultados if not r.passou]}")
        if criticas:
            raise RuntimeError(f"regras críticas falharam: {criticas}")
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        erros["fi_inf_diario"] = repr(ex)

# COMMAND ----------

# MAGIC %md ## Fundos imobiliários: informe mensal (SCD1)

# COMMAND ----------

def num(c: str, tipo: str) -> str:
    """Texto da CVM para número; aceita notação científica (ex.: 2.5E-05)."""
    return f"try_cast({txt(c)} AS DOUBLE)" if tipo == "DOUBLE" else f"CAST(try_cast({txt(c)} AS DOUBLE) AS {tipo})"


def num_valido(c: str) -> str:
    return f"({txt(c)} IS NULL OR try_cast({txt(c)} AS DOUBLE) IS NOT NULL)"


if p.escolhida("fii_inf_mensal"):
    bronze_c = f"{k}.bronze.cvm_fii_inf_mensal_complemento"
    bronze_g = f"{k}.bronze.cvm_fii_inf_mensal_geral"
    destino = f"{k}.silver.cvm_fii_mensal"
    e = control.Execucao(k, p.run_id, "silver_cvm", FONTE, "fii_inf_mensal", "silver", p.run_mode)
    control.iniciar(spark, e)
    c = control.Contagens()
    try:
        numericas = ["total_numero_cotistas", "valor_ativo", "patrimonio_liquido", "cotas_emitidas",
                     "valor_patrimonial_cotas", "percentual_despesas_taxa_administracao",
                     "percentual_rentabilidade_efetiva_mes", "percentual_rentabilidade_patrimonial_mes",
                     "percentual_dividend_yield_mes", "percentual_amortizacao_cotas_mes", "versao"]
        valido = " AND ".join(["_corrupt_record IS NULL", f"length({cnpj('cnpj_fundo_classe')}) = 14",
                               f"{dt('data_referencia')} IS NOT NULL"] + [num_valido(x) for x in numericas])
        pend = sql_pendentes(bronze_c, k, FONTE, "fii_inf_mensal", "true", reprocessar)
        spark.sql(f"SELECT *, coalesce(({valido}), false) AS _valido FROM ({pend})").createOrReplaceTempView("_fii_pend")
        c.read = spark.table("_fii_pend").count()
        invalidos = spark.table("_fii_pend").where("NOT _valido").drop("_valido")
        c.rejected = invalidos.count()
        if c.rejected:
            invalidos.write.mode("append").json(caminho_quarentena(k, FONTE, "fii_inf_mensal", hoje, p.run_id))
        colunas = ["versao", "data_entrega", "tipo_fundo_classe", "nome_fundo", "segmento_atuacao", "mandato",
                   "tipo_gestao", "publico_alvo", "codigo_isin", "negociado_bolsa", "nome_administrador",
                   "cnpj_administrador", "cotistas", "valor_ativo", "patrimonio_liquido", "cotas_emitidas",
                   "valor_patrimonial_cota", "taxa_administracao_mes", "rentab_efetiva_mes",
                   "rentab_patrimonial_mes", "dividend_yield_mes", "amortizacao_mes"]
        spark.sql(f"""
            SELECT cnpj_classe, data_referencia, {', '.join(colunas)},
                   {expr_hash(colunas)} AS record_hash, '{p.run_id}' AS _pipeline_run_id
            FROM (
              SELECT {cnpj('c.cnpj_fundo_classe')} AS cnpj_classe, {dt('c.data_referencia')} AS data_referencia,
                     CAST(try_cast({txt('c.versao')} AS DOUBLE) AS INT) AS versao,
                     {dt('g.data_entrega')} AS data_entrega, {txt('g.tipo_fundo_classe')} AS tipo_fundo_classe,
                     {txt('g.nome_fundo_classe')} AS nome_fundo, {txt('g.segmento_atuacao')} AS segmento_atuacao,
                     {txt('g.mandato')} AS mandato, {txt('g.tipo_gestao')} AS tipo_gestao,
                     {txt('g.publico_alvo')} AS publico_alvo, {txt('g.codigo_isin')} AS codigo_isin,
                     {txt('g.mercado_negociacao_bolsa')} AS negociado_bolsa,
                     {txt('g.nome_administrador')} AS nome_administrador,
                     {cnpj('g.cnpj_administrador')} AS cnpj_administrador,
                     {num('c.total_numero_cotistas', 'INT')} AS cotistas,
                     {num('c.valor_ativo', 'DECIMAL(20,2)')} AS valor_ativo,
                     {num('c.patrimonio_liquido', 'DECIMAL(20,2)')} AS patrimonio_liquido,
                     {num('c.cotas_emitidas', 'DECIMAL(24,6)')} AS cotas_emitidas,
                     {num('c.valor_patrimonial_cotas', 'DECIMAL(27,12)')} AS valor_patrimonial_cota,
                     {num('c.percentual_despesas_taxa_administracao', 'DOUBLE')} AS taxa_administracao_mes,
                     {num('c.percentual_rentabilidade_efetiva_mes', 'DOUBLE')} AS rentab_efetiva_mes,
                     {num('c.percentual_rentabilidade_patrimonial_mes', 'DOUBLE')} AS rentab_patrimonial_mes,
                     {num('c.percentual_dividend_yield_mes', 'DOUBLE')} AS dividend_yield_mes,
                     {num('c.percentual_amortizacao_cotas_mes', 'DOUBLE')} AS amortizacao_mes,
                     c._ingestion_timestamp, c._record_hash
              FROM _fii_pend c
              LEFT JOIN {bronze_g} g
                ON g._file_hash = c._file_hash AND g.cnpj_fundo_classe = c.cnpj_fundo_classe
               AND g.data_referencia = c.data_referencia AND g.versao = c.versao
              WHERE c._valido
            )
            -- reenvios: fica a versão mais alta; na mesma versão, a carga mais recente
            QUALIFY row_number() OVER (PARTITION BY cnpj_classe, data_referencia
                                       ORDER BY versao DESC, _ingestion_timestamp DESC, _record_hash) = 1
        """).createOrReplaceTempView("_fii_src")
        n_validos = spark.table("_fii_src").count()
        c.inserted, c.updated = executar_merge(spark, merge_scd1(
            destino, "_fii_src", ["cnpj_classe", "data_referencia"], colunas))
        c.unchanged = n_validos - c.inserted - c.updated
        da_execucao = f"SELECT * FROM {destino} WHERE _pipeline_run_id = '{p.run_id}'"
        regras = [
            dq.Regra("chave_unica", "Uma linha por (CNPJ, mês)", "CRITICAL", destino,
                     f"SELECT cnpj_classe, data_referencia, count(*) n FROM {destino} GROUP BY ALL HAVING n > 1",
                     f"SELECT count(*) FROM {destino}"),
            dq.Regra("formato_api", "CNPJ, data e números convertíveis; linha com o número certo de campos", "HIGH",
                     bronze_c, "SELECT * FROM _fii_pend WHERE NOT _valido", "SELECT count(*) FROM _fii_pend"),
            dq.Regra("complemento_sem_geral", "Informe sem a linha correspondente no ficheiro geral (nome, segmento)",
                     "INFO", destino,
                     f"SELECT cnpj_classe, data_referencia FROM ({da_execucao}) WHERE nome_fundo IS NULL",
                     f"SELECT count(*) FROM ({da_execucao})"),
            dq.Regra("percentual_suspeito", "Rentabilidade ou DY acima de ±50 % no mês (provável unidade errada)",
                     "INFO", destino,
                     f"SELECT cnpj_classe, data_referencia, rentab_efetiva_mes, dividend_yield_mes FROM ({da_execucao}) "
                     f"WHERE abs(rentab_efetiva_mes) > 0.5 OR abs(dividend_yield_mes) > 0.5",
                     f"SELECT count(*) FROM ({da_execucao})"),
        ]
        resultados = dq.avaliar(spark, regras)
        dq.gravar(spark, k, p.run_id, resultados)
        criticas = [r.regra.nome for r in resultados if not r.passou and r.regra.severidade == "CRITICAL"]
        maximo = spark.sql(f"SELECT max(data_referencia) FROM {destino}").first()[0]
        if maximo and not criticas:
            control.confirmar_watermark(spark, e, "reference_date", maximo.isoformat(), None)
        control.concluir(spark, e, c)
        print(f"fii_inf_mensal: lidos={c.read} novos={c.inserted} alterados={c.updated} iguais={c.unchanged} "
              f"rejeitados={c.rejected} watermark={maximo} falhas={[r.regra.nome for r in resultados if not r.passou]}")
        if criticas:
            raise RuntimeError(f"regras críticas falharam: {criticas}")
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        erros["fii_inf_mensal"] = repr(ex)

# COMMAND ----------

# MAGIC %md ## Cadastros (SCD2)

# COMMAND ----------

CADASTROS = {
    # entidade silver: (entidade bronze, tabela bronze, chaves, SELECT sobre a vista _snap)
    "cvm_fundo": ("fi_registro", "cvm_fi_registro_fundo", ["id_registro_fundo"], f"""
        SELECT {txt('id_registro_fundo')} AS id_registro_fundo, {cnpj('cnpj_fundo')} AS cnpj_fundo,
               {txt('codigo_cvm')} AS codigo_cvm, {txt('tipo_fundo')} AS tipo_fundo,
               {txt('denominacao_social')} AS denominacao_social, {txt('situacao')} AS situacao,
               {dt('data_registro')} AS data_registro, {dt('data_constituicao')} AS data_constituicao,
               {dt('data_cancelamento')} AS data_cancelamento, {dt('data_inicio_situacao')} AS data_inicio_situacao,
               {dt('data_adaptacao_rcvm175')} AS data_adaptacao_rcvm175,
               {cnpj('cnpj_administrador')} AS cnpj_administrador, {txt('administrador')} AS administrador
        FROM _snap GROUP BY ALL"""),
    "cvm_fundo_gestor": ("fi_registro", "cvm_fi_registro_fundo", ["id_registro_fundo", "cnpj_gestor"], f"""
        SELECT {txt('id_registro_fundo')} AS id_registro_fundo, {cnpj('cpf_cnpj_gestor')} AS cnpj_gestor,
               min({txt('gestor')}) AS gestor
        FROM _snap WHERE trim(tipo_pessoa_gestor) = 'PJ' AND {cnpj('cpf_cnpj_gestor')} IS NOT NULL
        GROUP BY 1, 2"""),
    "cvm_fundo_classe": ("fi_registro", "cvm_fi_registro_classe", ["id_registro_classe"], f"""
        SELECT {txt('id_registro_classe')} AS id_registro_classe, {txt('id_registro_fundo')} AS id_registro_fundo,
               {cnpj('cnpj_classe')} AS cnpj_classe, {txt('codigo_cvm')} AS codigo_cvm,
               {txt('tipo_classe')} AS tipo_classe, {txt('denominacao_social')} AS denominacao_social,
               {txt('situacao')} AS situacao, {dt('data_registro')} AS data_registro,
               {dt('data_inicio')} AS data_inicio, {dt('data_inicio_situacao')} AS data_inicio_situacao,
               {txt('classificacao')} AS classificacao, {txt('classificacao_anbima')} AS classificacao_anbima,
               {txt('publico_alvo')} AS publico_alvo, {txt('forma_condominio')} AS forma_condominio,
               {txt('exclusivo')} AS exclusivo, {cnpj('cnpj_auditor')} AS cnpj_auditor, {txt('auditor')} AS auditor,
               nullif(array_join(sort_array(collect_set({txt('custodiante')})), ' | '), '') AS custodiantes,
               nullif(array_join(sort_array(collect_set({txt('controlador')})), ' | '), '') AS controladores
        FROM _snap GROUP BY ALL"""),
    "cvm_companhia": ("cia_aberta_cad", "cvm_cia_aberta_cad", ["cd_cvm"], f"""
        SELECT {txt('cd_cvm')} AS cd_cvm, {cnpj('cnpj_cia')} AS cnpj_cia, {txt('denom_social')} AS denom_social,
               {txt('denom_comerc')} AS denom_comerc, {dt('dt_reg')} AS dt_reg, {dt('dt_const')} AS dt_const,
               {dt('dt_cancel')} AS dt_cancel, {txt('motivo_cancel')} AS motivo_cancel, {txt('sit')} AS sit,
               {dt('dt_ini_sit')} AS dt_ini_sit, {txt('setor_ativ')} AS setor_ativ,
               nullif(array_join(sort_array(collect_set({txt('tp_merc')})), ' | '), '') AS tp_merc,
               {txt('categ_reg')} AS categ_reg, {txt('sit_emissor')} AS sit_emissor,
               {txt('controle_acionario')} AS controle_acionario, {txt('mun')} AS mun, {txt('uf')} AS uf,
               {txt('pais')} AS pais, {cnpj('cnpj_auditor')} AS cnpj_auditor, {txt('auditor')} AS auditor
        FROM _snap GROUP BY ALL"""),
}

for entidade, (ent_bronze, tab_bronze, chaves, select_sql) in CADASTROS.items():
    if not (p.escolhida(entidade) or p.escolhida(ent_bronze)):
        continue
    destino = f"{k}.silver.{entidade}"
    e = control.Execucao(k, p.run_id, "silver_cvm", FONTE, entidade, "silver", p.run_mode)
    control.iniciar(spark, e)
    c = control.Contagens()
    try:
        # pendente por entidade silver: cada cadastro tem o seu histórico de execuções
        pend = sql_pendentes(f"{k}.bronze.{tab_bronze}", k, FONTE, entidade, "true", reprocessar)
        spark.sql(f"WITH p AS ({pend}), u AS (SELECT max_by(_file_hash, _ingestion_timestamp) AS h FROM p) "
                  f"SELECT p.* FROM p JOIN u ON p._file_hash = u.h").createOrReplaceTempView("_snap")
        c.read = spark.table("_snap").count()
        if c.read == 0:
            control.concluir(spark, e, c, control.STATUS_SKIPPED)
            print(f"{entidade}: sem snapshot novo")
            continue
        df = spark.sql(select_sql)
        atributos = [x for x in df.columns if x not in chaves]
        (df.selectExpr("*", f"{expr_hash(atributos)} AS record_hash", f"'{p.run_id}' AS _pipeline_run_id")
           .createOrReplaceTempView("_cad_src"))
        regras = [dq.Regra("chave_unica", f"Uma linha por {chaves} no snapshot", "CRITICAL", destino,
                           f"SELECT {', '.join(chaves)}, count(*) n FROM _cad_src GROUP BY ALL HAVING n > 1",
                           "SELECT count(*) FROM _cad_src"),
                  dq.Regra("chave_preenchida", f"{chaves} sem valores vazios", "CRITICAL", destino,
                           f"SELECT * FROM _cad_src WHERE {' OR '.join(f'{x} IS NULL' for x in chaves)}",
                           "SELECT count(*) FROM _cad_src")]
        resultados = dq.avaliar(spark, regras)
        dq.gravar(spark, k, p.run_id, resultados)
        falhas = [r.regra.nome for r in resultados if not r.passou]
        if falhas:
            raise RuntimeError(f"regras críticas falharam em {entidade}: {falhas} {[r.amostra for r in resultados]}")
        c.inserted, c.updated = executar_merge(spark, merge_scd2(destino, "_cad_src", chaves, atributos))
        _, fechados = executar_merge(spark, fechar_ausentes_scd2(destino, "_cad_src", chaves))
        c.deleted = fechados
        control.concluir(spark, e, c)
        print(f"{entidade}: snapshot={c.read} linhas, chaves={spark.table('_cad_src').count()} "
              f"versões novas={c.inserted} alteradas={c.updated} ausentes fechadas={c.deleted}")
    except Exception as ex:
        control.falhar(spark, e, ex, c)
        erros[entidade] = repr(ex)

if erros:
    raise RuntimeError(f"falharam {len(erros)} entidades: {erros}")
