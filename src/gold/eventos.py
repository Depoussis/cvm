"""Fator de evento da B3: o único sítio que decide quanto vale cada desdobramento, grupamento e bonificação.

Produz `gold.fct_evento_acao`: uma linha por ticker e pregão em que um evento entra (a data ex), com o fator de
preço (preço depois = preço antes x fator, sem variação de mercado), a origem e o detalhe. Todos os consumidores
leem esta tabela: `fct_cotacao_diaria.fator_evento` e o preço ajustado (src/gold/cotacoes.py), o `fator_posterior`
dos proventos, o simulador (pela coluna das cotações) e a validação externa.

Regras (as mesmas desde 16/10/2026; ver docs/pipelines_b3.md):
- **B3** (`silver.b3_evento_acao`, ligada ao ticker pelo ISIN): desdobramento f % → 1 / (1 + f/100); bonificação
  f % → 1 / (1 + f/100); grupamento f (fração) → 1 / f.
- **Complementar** (config/datasets/b3_eventos_complementares.yaml): bonificações que a API da B3 não publica; valem
  para todas as ações do emissor e são ignoradas se a B3 já tiver um evento desse ticker com a mesma data com.
- A data ex de um evento é o primeiro pregão do ticker depois da data com (só se houver pregão até à data com).
  Vários eventos que entram no mesmo pregão multiplicam-se (ex.: desdobramento 9900 % + grupamento 0,01 = 1).
- **Heurística**, só para papéis sem dados oficiais (FII, ETF, ações de emissores fora da carga de proventos): no
  pregão em que muda o número de distribuição do COTAHIST, uma variação do fecho a menos de 8 % de um fator inteiro
  (preço a cair k vezes → 1/k; a subir k vezes → k).

O cálculo é SQL; é testado no Databricks pelos testes de integração (notebooks/tests/integracao.py) com casos reais.
"""
from __future__ import annotations

from src.common.config import carregar_yaml

EVENTOS_OFICIAIS = ("DESDOBRAMENTO", "GRUPAMENTO", "BONIFICACAO")
TABELA = "gold.fct_evento_acao"


def bonificacoes_complementares() -> list[dict]:
    """Bonificações que a B3 não publica na API (config/datasets/b3_eventos_complementares.yaml)."""
    linhas = carregar_yaml("datasets/b3_eventos_complementares.yaml").get("bonificacoes") or []
    for b in linhas:
        if not (len(str(b["emissor"])) == 4 and float(b["percentual"]) > 0):
            raise ValueError(f"bonificação complementar inválida: {b}")
    return linhas


def _sql_oficiais(k: str) -> str:
    """Eventos oficiais por ticker e data com: B3 mais complementares (com origem e descrição)."""
    tipos = ", ".join(f"'{t}'" for t in EVENTOS_OFICIAIS)
    valores = ", ".join(f"('{b['emissor']}', DATE'{b['data_com']}', {float(b['percentual'])})"
                        for b in bonificacoes_complementares()) or "(NULL, NULL, NULL)"
    b3 = f"""
  SELECT a.ticker, o.data_com, o.tipo_evento, CAST(o.fator AS DOUBLE) AS fator, 'B3' AS origem
  FROM {k}.silver.b3_evento_acao o
  JOIN {k}.gold.dim_ativo_b3 a ON a.isin = o.isin
  WHERE o.tipo_evento IN ({tipos}) AND o.fator > 0"""
    return f"""
SELECT ticker, data_com, tipo_evento, fator, origem,
       CASE WHEN tipo_evento = 'GRUPAMENTO' THEN 1.0 / fator ELSE 1.0 / (1.0 + fator / 100.0) END AS fator_preco
FROM ({b3}
  UNION ALL
  SELECT a.ticker, c.data_com, 'BONIFICACAO' AS tipo_evento, CAST(c.percentual AS DOUBLE) AS fator,
         'complementar' AS origem
  FROM (VALUES {valores}) AS c(emissor, data_com, percentual)
  JOIN {k}.gold.dim_ativo_b3 a ON substr(a.ticker, 1, 4) = c.emissor AND a.classe_ativo = 'Ação'
  LEFT ANTI JOIN ({b3}) o ON o.ticker = a.ticker AND o.data_com = c.data_com
) eventos"""


def sql_cobertura_oficial(k: str) -> str:
    """Tickers cujos eventos vêm da B3: ações de emissores presentes na carga de proventos (sem heurística)."""
    return f"""
SELECT a.ticker FROM {k}.gold.dim_ativo_b3 a
WHERE a.classe_ativo = 'Ação' AND substr(a.ticker, 1, 4) IN (SELECT emissor FROM {k}.silver.b3_empresa)"""


def sql_eventos(k: str) -> str:
    """Todas as linhas de gold.fct_evento_acao, calculadas de raiz a partir da silver e da configuração."""
    return f"""
WITH b AS (
  SELECT ticker, data_pregao, preco_fechamento, distribuicao,
         lag(preco_fechamento) OVER w AS fecho_anterior, lag(distribuicao) OVER w AS distribuicao_anterior,
         lag(data_pregao) OVER w AS pregao_anterior
  FROM {k}.silver.b3_cotacao_diaria
  WHERE coalesce(especificacao, '') NOT LIKE 'IBO%'   -- IBOV11: cesta do Ibovespa, não é uma ação
  WINDOW w AS (PARTITION BY ticker ORDER BY data_pregao)
),
oficial AS ({_sql_oficiais(k)}),
cobertura AS ({sql_cobertura_oficial(k)}),
oficial_ex AS (   -- evento oficial → pregão em que entra (primeiro depois da data com)
  SELECT b.ticker, b.data_pregao AS data_ex, max(o.data_com) AS data_com,
         exp(sum(ln(o.fator_preco))) AS fator,
         array_join(array_sort(collect_set(o.origem)), '+') AS origem,
         array_join(array_sort(collect_list(concat(o.tipo_evento, ' ', CAST(o.fator AS STRING), ' (',
                                                   CAST(o.data_com AS STRING), ')'))), '; ') AS detalhe
  FROM b JOIN oficial o ON o.ticker = b.ticker AND o.data_com >= b.pregao_anterior AND o.data_com < b.data_pregao
  GROUP BY b.ticker, b.data_pregao
),
cand AS (         -- heurística: fator inteiro mais próximo da variação do fecho
  SELECT b.*, CAST(preco_fechamento AS DOUBLE) / CAST(fecho_anterior AS DOUBLE) AS razao
  FROM b LEFT ANTI JOIN cobertura c ON c.ticker = b.ticker
  WHERE fecho_anterior > 0 AND preco_fechamento > 0 AND distribuicao <> distribuicao_anterior
),
heuristica AS (
  SELECT ticker, data_pregao AS data_ex, pregao_anterior AS data_com, CAST(candidato AS DOUBLE) AS fator,
         'heurística' AS origem,
         concat('variação do fecho ', CAST(round(razao, 4) AS STRING), ' com mudança de distribuição') AS detalhe
  FROM (SELECT cand.*, CASE WHEN razao < 0.6 THEN 1.0 / round(1.0 / razao)
                            WHEN razao > 1.6 THEN round(razao) END AS candidato FROM cand)
  WHERE candidato BETWEEN 0.001 AND 1000 AND abs(razao / candidato - 1) <= 0.08
)
SELECT ticker, data_ex, data_com, fator, origem, detalhe FROM oficial_ex
UNION ALL
SELECT h.ticker, h.data_ex, h.data_com, h.fator, h.origem, h.detalhe FROM heuristica h
LEFT ANTI JOIN oficial_ex o ON o.ticker = h.ticker AND o.data_ex = h.data_ex"""


def sql_alterados(k: str, novos: str) -> str:
    """Tickers cujos eventos mudaram entre a tabela atual e `novos` (vista com as mesmas colunas), com a primeira
    data ex afetada: são os que a gold das cotações tem de recalcular a partir dessa data."""
    return f"""
SELECT coalesce(n.ticker, a.ticker) AS ticker, min(coalesce(n.data_ex, a.data_ex)) AS d0
FROM {novos} n FULL OUTER JOIN {k}.{TABELA} a ON a.ticker = n.ticker AND a.data_ex = n.data_ex
WHERE n.ticker IS NULL OR a.ticker IS NULL OR abs(n.fator - a.fator) > 1e-12 * a.fator
GROUP BY 1"""


def sql_fator_posterior(k: str, ticker: str, depois_de: str) -> str:
    """Produto dos fatores dos eventos do `ticker` com data ex depois de `depois_de` (expressões SQL): converte um
    valor da data com (provento, preço) para a base de ações de hoje."""
    return (f"(SELECT coalesce(exp(sum(ln(e.fator))), 1.0) FROM {k}.{TABELA} e "
            f"WHERE e.ticker = {ticker} AND e.data_ex > {depois_de})")


def sql_diferencas(k: str) -> str:
    """Eventos em que a tabela difere de um cálculo de raiz (deve dar zero): para os testes de integração."""
    return f"""
WITH esperado AS ({sql_eventos(k)})
SELECT coalesce(e.ticker, t.ticker) AS ticker, coalesce(e.data_ex, t.data_ex) AS data_ex,
       e.fator AS esperado, t.fator AS obtido
FROM esperado e FULL OUTER JOIN {k}.{TABELA} t ON e.ticker = t.ticker AND e.data_ex = t.data_ex
WHERE e.ticker IS NULL OR t.ticker IS NULL OR abs(e.fator - t.fator) > 1e-12 * e.fator"""
