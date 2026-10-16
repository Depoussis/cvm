"""Fundamentos trimestrais a partir das contas da DFP/ITR (silver.cvm_demo_conta). Partilhado pelo notebook
gold/cvm_fundamentos e pelos testes.

Identificação das contas pela descrição padronizada no nível certo, porque o código muda com o tipo de empresa:

| Métrica | Regra | Exemplos de código |
|---|---|---|
| receita | conta 3.01 | indústria "Receita de Venda...", banco "Receitas da Intermediação Financeira" |
| lucro | nível 2 "Lucro/Prejuízo ... do Período"; se houver, o filho "Atribuído a Sócios da Empresa Controladora" | 3.11 / 3.11.01 indústria, 3.09 banco, 3.13 seguradora |
| LAIR | nível 2 "Resultado Antes dos Tributos sobre o Lucro" | 3.07, 3.05, 3.09 |
| PL | nível 2 "Patrimônio Líquido..." menos o filho "Participação dos Acionistas Não Controladores" | 2.03, 2.08 |
| dívida | nível 3 "Empréstimos e Financiamentos" no circulante e não circulante | 2.01.04 + 2.02.01 |
| caixa | nível 3 de 1.01 "Caixa e Equivalentes..." + "Aplicações Financeiras" | 1.01.01 + 1.01.02 |

As regras usam só a sintaxe [0-9] (sem chavetas) porque o SQL passa por str.format.
"""
from __future__ import annotations

NIVEL2_DRE = "cd_conta rlike '^3[.][0-9][0-9]$'"
NIVEL3_DRE = "cd_conta rlike '^3[.][0-9][0-9][.][0-9][0-9]$'"
RE_LUCRO = "(?i)^lucro.?.?.?.?preju[ií]zo.*(per[ií]odo|exerc)"
RE_CONTROLADORA = "(?i)atribu[ií]do a s[óo]cios da (empresa )?controladora"
RE_LAIR = "(?i)^resultado antes dos tributos"
RE_PL = "(?i)^patrim[ôo]nio l[ií]quido"
RE_NAO_CONTROLADORES = "(?i)n[ãa]o controladores"
RE_DIVIDA = "(?i)^empr[ée]stimos e financiamentos"
RE_CAIXA = "(?i)^(caixa e equivalentes|aplica[çc][õo]es financeiras)"

SQL_FUNDAMENTOS = f"""
WITH docs AS (
  SELECT cnpj_cia, tipo_doc, dt_refer, min(dt_receb) AS data_publicacao, max(versao) AS versao_max
  FROM {{k}}.silver.cvm_demo_documento GROUP BY 1, 2, 3
),
c AS (
  SELECT c.* FROM {{k}}.silver.cvm_demo_conta c
  JOIN docs d ON d.cnpj_cia = c.cnpj_cia AND d.tipo_doc = c.tipo_doc AND d.dt_refer = c.dt_refer
  WHERE c.versao = d.versao_max
),
esc AS (   -- consolidado quando a DRE consolidada existe; senão individual
  SELECT cnpj_cia, tipo_doc, dt_refer,
         CASE WHEN count_if(escopo = 'con' AND demonstracao = 'DRE') > 0 THEN 'con' ELSE 'ind' END AS escopo
  FROM c GROUP BY 1, 2, 3
),
cc AS (SELECT c.* FROM c JOIN esc USING (cnpj_cia, tipo_doc, dt_refer, escopo)),
dre AS (
  SELECT cnpj_cia, tipo_doc, dt_refer, escopo, dt_ini_exerc, dt_fim_exerc,
         round(months_between(date_add(dt_fim_exerc, 1), dt_ini_exerc)) AS meses,
         max(CASE WHEN cd_conta = '3.01' THEN valor END) AS receita,
         coalesce(max(CASE WHEN {NIVEL3_DRE} AND ds_conta rlike '{RE_CONTROLADORA}' THEN valor END),
                  max(CASE WHEN {NIVEL2_DRE} AND ds_conta rlike '{RE_LUCRO}' THEN valor END)) AS lucro,
         max(CASE WHEN {NIVEL2_DRE} AND ds_conta rlike '{RE_LAIR}' THEN valor END) AS lair
  FROM cc WHERE demonstracao = 'DRE'
  GROUP BY 1, 2, 3, 4, 5, 6
),
q3m AS (   -- trimestres da ITR (3 meses)
  SELECT cnpj_cia, dt_fim_exerc AS dt_fim, dt_ini_exerc, 'ITR' AS documento, escopo, receita, lucro, lair
  FROM dre WHERE tipo_doc = 'ITR' AND meses = 3 AND dt_fim_exerc = dt_refer
),
anual AS (
  SELECT cnpj_cia, dt_ini_exerc, dt_fim_exerc, escopo, receita, lucro, lair
  FROM dre WHERE tipo_doc = 'DFP' AND meses = 12 AND dt_fim_exerc = dt_refer
),
q4 AS (    -- 4.º trimestre = anual - três trimestres do mesmo exercício (só com os três)
  SELECT a.cnpj_cia, a.dt_fim_exerc AS dt_fim, add_months(date_add(a.dt_fim_exerc, 1), -3) AS dt_ini_exerc,
         'DFP' AS documento, a.escopo,
         a.receita - sum(q.receita) AS receita, a.lucro - sum(q.lucro) AS lucro, a.lair - sum(q.lair) AS lair
  FROM anual a JOIN q3m q ON q.cnpj_cia = a.cnpj_cia AND q.dt_fim > a.dt_ini_exerc AND q.dt_fim < a.dt_fim_exerc
  GROUP BY a.cnpj_cia, a.dt_fim_exerc, a.escopo, a.receita, a.lucro, a.lair
  HAVING count(*) = 3
),
tri AS (   -- algumas empresas também entregam uma ITR do 4.º trimestre: fica a DFP (anual, auditada)
  SELECT * FROM (SELECT * FROM q3m UNION ALL SELECT * FROM q4)
  QUALIFY row_number() OVER (PARTITION BY cnpj_cia, dt_fim ORDER BY CASE documento WHEN 'DFP' THEN 0 ELSE 1 END) = 1
),
ttm AS (
  SELECT t.*,
         CASE WHEN lag(dt_fim, 3) OVER w = last_day(add_months(dt_fim, -9))
              THEN sum(receita) OVER (PARTITION BY cnpj_cia ORDER BY dt_fim ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) END AS receita_12m,
         CASE WHEN lag(dt_fim, 3) OVER w = last_day(add_months(dt_fim, -9))
              THEN sum(lucro) OVER (PARTITION BY cnpj_cia ORDER BY dt_fim ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) END AS lucro_12m
  FROM tri t
  WINDOW w AS (PARTITION BY cnpj_cia ORDER BY dt_fim)
),
bal AS (
  SELECT cnpj_cia, tipo_doc, dt_refer,
         max(CASE WHEN demonstracao = 'BPA' AND cd_conta = '1' THEN valor END) AS ativo_total,
         max(CASE WHEN demonstracao = 'BPP' AND cd_conta rlike '^2[.][0-9][0-9]$' AND ds_conta rlike '{RE_PL}'
                  THEN valor END) AS pl_consolidado,
         max(CASE WHEN demonstracao = 'BPP' AND cd_conta rlike '^2[.][0-9][0-9][.][0-9][0-9]$'
                       AND ds_conta rlike '{RE_NAO_CONTROLADORES}' THEN valor END) AS pl_nao_controladores,
         sum(CASE WHEN demonstracao = 'BPP' AND cd_conta rlike '^2[.]0[12][.][0-9][0-9]$' AND ds_conta rlike '{RE_DIVIDA}'
                  THEN valor END) AS divida_bruta,
         sum(CASE WHEN demonstracao = 'BPA' AND cd_conta rlike '^1[.]01[.][0-9][0-9]$' AND ds_conta rlike '{RE_CAIXA}'
                  THEN valor END) AS caixa
  FROM cc WHERE demonstracao IN ('BPA', 'BPP') AND dt_fim_exerc = dt_refer
  GROUP BY 1, 2, 3
)
SELECT t.cnpj_cia, t.dt_fim, t.documento, t.escopo, d.data_publicacao,
       CAST(t.receita AS DECIMAL(24, 2)), CAST(t.lucro AS DECIMAL(24, 2)), CAST(t.lair AS DECIMAL(24, 2)),
       CAST(t.receita_12m AS DECIMAL(24, 2)), CAST(t.lucro_12m AS DECIMAL(24, 2)),
       b.ativo_total, CAST(b.pl_consolidado - coalesce(b.pl_nao_controladores, 0) AS DECIMAL(24, 2)),
       b.divida_bruta, b.caixa,
       cap.acoes_on - coalesce(cap.tesouraria_on, 0), cap.acoes_pn - coalesce(cap.tesouraria_pn, 0),
       cap.acoes_total - coalesce(cap.tesouraria_total, 0)
FROM ttm t
LEFT JOIN docs d ON d.cnpj_cia = t.cnpj_cia AND d.tipo_doc = t.documento AND d.dt_refer = t.dt_fim
LEFT JOIN bal b ON b.cnpj_cia = t.cnpj_cia AND b.tipo_doc = t.documento AND b.dt_refer = t.dt_fim
LEFT JOIN {{k}}.silver.cvm_demo_capital cap
  ON cap.cnpj_cia = t.cnpj_cia AND cap.tipo_doc = t.documento AND cap.dt_refer = t.dt_fim
"""
