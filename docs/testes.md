# Casos de teste: B3, streaming, fundamentos e modelo preditivo

Catálogo dos testes da integração da B3 (cotações da bolsa) e do streaming (Auto Loader e Change Data Feed),
executados em 16/10/2026 no ambiente `dev` (catálogo `findata_dev`, workspace `dbw-findata-dev`). Cada caso diz o
que verifica, como se repete, o resultado esperado, o obtido e a evidência (IDs das execuções no Databricks).

| Tipo | Prefixo | Onde corre | Quando |
|---|---|---|---|
| Unitário | TU | `pytest`, sem Spark nem rede | em cada alteração e no CI (`azure-pipelines.yml`) |
| Integração | TI | `notebooks/tests/integracao.py`, job `findata_dev_auditoria` | semanal (domingo) e no CD |
| Funcional (pipeline) | TF | jobs `findata_dev_b3` e `findata_dev_cvm` | manual, com os passos indicados |
| Validação de dados | TD | consultas SQL no warehouse | manual, depois de uma carga |
| Painel | TP | Streamlit local (`localhost:8502`) e publicado | manual, no browser |

Os conceitos usados nestes testes (Auto Loader, checkpoint, watermark, deduplicação, Delta Lake, Change Data Feed,
SCD) estão explicados em [conceitos.md](conceitos.md).

Resumo: **9 TU, 1 TI, 11 TF, 9 TD e 5 TP, todos aprovados**. Os 3 defeitos encontrados durante os testes foram
corrigidos e estão descritos no fim.

---

## Testes unitários (`tests/unit/test_b3.py`)

```bash
.venv/Scripts/python -m pytest tests/unit/test_b3.py -v
```

| ID | Teste | Verifica | Estado |
|---|---|---|---|
| TU-01 | `test_layout_cobre_as_245_posicoes_sem_buracos` | os 26 campos do layout COTAHIST são contíguos e cobrem exatamente 245 posições | aprovado |
| TU-02 | `test_parse_linha_real` | uma linha real (PETR4 de 15/10/2026) dá data, BDI, ticker, mercado, especificação e ISIN certos; casas decimais implícitas (`0000000005736` → 57,36), volume, negócios e fator de cotação; campo vazio → `None` | aprovado |
| TU-03 | `test_expressoes_spark_usam_as_mesmas_posicoes` | o `SELECT` de Spark usa as mesmas posições do layout (ex.: `substring(linha, 13, 12) AS codneg`) | aprovado |
| TU-04 | `test_alvos_por_modo` | backfill → anuais 2021 a 2026; incremental → diários só em dias úteis, terminando hoje; reprocess → anuais do intervalo; reprocess sem datas → erro | aprovado |
| TU-05 | `test_envelope_e_trailer` | trailer com o total igual ao nº de cotações é aceite, e também total + 2 (leitura do layout); total diferente → problema; ficheiro sem trailer (truncado) → problema | aprovado |
| TU-06 | `test_extrair_txt_em_blocos_e_rejeita_zip_inesperado` | extrai o único TXT do ZIP para um ficheiro em blocos; ZIP com dois TXT → erro | aprovado |
| TU-07 | `test_ler_envelope_em_fluxo` | lê cabeçalho, trailer e conta os registos 01 sem carregar o ficheiro em memória; o resultado passa na validação | aprovado |
| TU-08 | `test_chave_liga_txt_do_auto_loader_ao_zip_registado` | o TXT lido pelo Auto Loader (`dbfs:/…/job-1/extraidos/X.TXT`) e o ZIP registado (`/…/job-1/X.ZIP`) dão a mesma chave | aprovado |
| TU-09 | `test_calculo_gold_reutilizado_pela_carga_incremental_e_pela_verificacao` | o SQL da gold aplica o filtro final, exclui a cesta IBOV11 e a consulta de diferenças compara gold e silver | aprovado |

Também cobrem a B3: `tests/unit/test_adf.py` (o pipeline diário referencia `job_id_b3`) e `tests/unit/test_config.py`.
Suite completa: **56 testes aprovados**.

---

## Teste de integração

| ID | TI-01: gold B3 incremental (CDF) igual à reconstrução completa |
|---|---|
| Objetivo | Garantir que a carga incremental da `gold.fct_cotacao_diaria` produz exatamente o mesmo que recalcular tudo a partir da silver |
| Como | `notebooks/tests/integracao.py` corre `src/gold/cotacoes.py: sql_diferencas`: reconstrução completa em memória, `FULL OUTER JOIN` com a gold, compara presença, `fator_evento`, `retorno_dia` e `preco_ajustado` (tolerância relativa 1e-9). Só leitura |
| Esperado | 0 linhas diferentes; se houver diferenças, a auditoria semanal falha |
| Obtido | 0 diferenças; tarefa `testes_integracao` SUCCESS |
| Evidência | job `findata_dev_auditoria`, run `1096980757605498` |

---

## Testes funcionais do pipeline

### Ingestão da B3

| ID | TF-01: backfill da B3 (ficheiros anuais 2021-2026) |
|---|---|
| Passos | `python scripts/deploy_workspace.py --env dev --fonte b3`, depois `run_now` do job `findata_dev_b3` com `run_mode=backfill` |
| Esperado | 6 ficheiros anuais `PROCESSED`, bronze → silver → gold com sucesso |
| Obtido | SUCCESS nas 3 tarefas. Bronze (mercado à vista) por ano: 2021 → 277 399; 2022 → 308 865; 2023 → 307 936; 2024 → 322 397; 2025 → 335 874; mais 2026. Gold: 1 272 346 linhas: 699 501 de ações (1 594 tickers), 395 698 de FII (661) e 177 452 de ETF e fundos (303), de 04/01/2021 a 15/10/2026 |
| Evidência | run `1121052296582267` |

| ID | TF-02: incremental com ficheiros diários |
|---|---|
| Passos | `python scripts/deploy_workspace.py --env dev --fonte b3 --run incremental` |
| Esperado | diários dos últimos 10 dias úteis descarregados; dias sem pregão ignorados |
| Obtido | 7 diários `PROCESSED` (06, 07, 08, 09, 13, 14 e 15/10). O feriado de 12/10 e o dia 16/10 (ainda não publicado) responderam 404 (`NAO_PUBLICADO`) |
| Evidência | run `536716794192256` |

| ID | TF-03: diário igual ao anual |
|---|---|
| Objetivo | O mesmo pregão chega no anual e no diário; a silver não pode mudar nem duplicar |
| Obtido | na TF-02, a silver leu 5 959 linhas pendentes: 0 novas, 0 alteradas. A regra CRITICAL `chave_unica` (pregão, ticker) passou |
| Evidência | `control.pipeline_execution`, `pipeline_run_id = 'job-536716794192256'` |

| ID | TF-04: ligação ticker → companhia (FCA da CVM) |
|---|---|
| Passos | job `findata_dev_cvm` com `run_mode=incremental` e `entidades=cia_aberta_fca` |
| Esperado | `silver.cvm_valor_mobiliario` com um ticker por linha, do FCA mais recente |
| Obtido | SUCCESS nas 4 tarefas; 533 tickers de 389 companhias (FCA 2025 e 2026) |
| Evidência | run `680796078329478` |

| ID | TF-05: pipeline diário do ADF inclui a B3 |
|---|---|
| Passos | `python scripts/deploy_adf.py --env dev` |
| Esperado | `pl_findata_diario` com a atividade `B3` em paralelo com BCB e CVM; a frescura depende das três |
| Obtido | publicado com `job_id_b3 = 1045656692787631` |

### Streaming

| ID | TF-06: Auto Loader carrega um ficheiro novo |
|---|---|
| Pré-condição | bronze já carregada pelo método anterior (migração) |
| Passos | 1) `UPDATE findata_dev.control.source_file_registry SET processing_status='FAILED', status_detail='teste do Auto Loader: forçar nova descarga' WHERE source_system='b3' AND reference_period='2026-10-15'`; 2) job B3 `incremental` |
| Esperado | o diário de 15/10 é descarregado de novo, fica `RECEIVED`, o Auto Loader carrega-o e marca-o `PROCESSED`; os TXT antigos não são relidos |
| Obtido | estado do ficheiro: `RECEIVED` (1); registo novo `PROCESSED` com "carregado pelo Auto Loader (lote 1)". Bronze de 15/10: 2 946 → 4 419 linhas (+1 473, as do ficheiro). Silver: 847 linhas lidas, 0 alterações |
| Evidência | run `580474600144089`; o registo marcado `FAILED` fica como rasto do teste |

| ID | TF-07: Auto Loader sem ficheiros novos |
|---|---|
| Esperado | os dois streams terminam sem carregar nada; nenhum ficheiro fica `RECEIVED` |
| Obtido | `auto_loader: {ficheiros: 0, linhas_bronze: 0}`; estados `SEM_ALTERACAO: 7`, `NAO_PUBLICADO: 2` |
| Evidência | run `123245314026063` |

| ID | TF-08: primeira execução da gold por Change Data Feed |
|---|---|
| Pré-condição | sem checkpoint em `ops/checkpoints/gold_b3_fct_cotacao` |
| Esperado | o CDF entrega a silver inteira; a gold é recalculada sem mudar valores |
| Obtido | versão 3 da gold: `MERGE` com 1 272 346 linhas atualizadas e 0 inseridas |
| Evidência | `DESCRIBE HISTORY findata_dev.gold.fct_cotacao_diaria`; run `580474600144089` |

| ID | TF-09: desdobramento novo detetado em incremental |
|---|---|
| Passos | `UPDATE findata_dev.silver.b3_cotacao_diaria SET preco_fechamento = 28.68, distribuicao = 231 WHERE ticker='PETR4' AND data_pregao='2026-10-15'` (era 57,36 e 230), depois só a tarefa `gold_b3` |
| Esperado | evento 2:1 detetado (`fator_evento = 0,5`); retorno do dia sem o efeito do desdobramento; histórico anterior da PETR4 com o preço ajustado dividido por 2; só a PETR4 recalculada |
| Obtido | fator 0,5; retorno −1,29 % (e não −50 %); preço ajustado em 14/10: 58,11 → 29,055. Delta: `MERGE` de 1 442 linhas (passado) + `MERGE` de 1 linha (pregão alterado) |
| Evidência | run `492130559376852`: as alterações foram aplicadas, mas a tarefa falhou depois do stream (defeito D-03) |

| ID | TF-10: desfazer o desdobramento |
|---|---|
| Passos | repor `preco_fechamento = 57.36, distribuicao = 230`; job B3 `incremental` completo |
| Esperado | fator volta a 1 e o passado volta ao valor original |
| Obtido | `change_data_feed: {lotes: 1, recalculadas: 1, passado_reajustado: 1442}`; preço ajustado em 14/10 de volta a 58,11 |
| Evidência | run `123245314026063` |

| ID | TF-11: gold incremental = reconstrução, depois de cada passo |
|---|---|
| Passos | `SELECT count(*) FROM (<sql_diferencas>)`, gerado por `src/gold/cotacoes.py` |
| Esperado | 0 |
| Obtido | 0 depois da TF-09 e 0 depois da TF-10 |

---

## Validação de dados

| ID | Caso | Consulta / verificação | Esperado | Obtido |
|---|---|---|---|---|
| TD-01 | Grupamento real detetado | `fct_cotacao_diaria`, MGLU3 em 27/05/2024 | fator 10 (R$ 1,32 → 13,15) | fator 10, retorno do dia −0,38 % |
| TD-02 | Queda real não é confundida com evento | AMER3 em 12/01/2023 | fator 1, retorno −77,3 % | fator 1, −0,773 (a distribuição não mudou: 101 → 101) |
| TD-03 | Eventos com fatores pouco comuns | `fator_evento <> 1` | rever casos | 290 eventos; ex.: BTYU11 ×82 (6,98 → 570, preço mantém-se depois), AZEV4 ×20 (0,11 → 2,22): consistentes com grupamentos |
| TD-04 | Espécie do FCA errada | `cvm_valor_mobiliario` da MGLU3 | ON | o FCA diz "Ações Preferenciais" (2025 e 2026) → a gold passou a usar a especificação da B3: `tipo_papel = ON` |
| TD-05 | Tickers mal preenchidos no FCA | bronze FCA da CSN, do BTG e da Klabin | ticker válido | CSN "4030", BTG "000000", Klabin só KLBN11 → fallback pela raiz de 4 letras: ações com emissor de 330 para 339 de 358 |
| TD-06 | Cesta do Ibovespa | IBOV11 na silver | não é ação | especificação `IBO/`, ~índice/100, negócios esporádicos (305 pregões) → excluída da gold |
| TD-07 | Valores de referência | `vw_b3_desempenho` | coerentes | PETR4 R$ 57,36 (PN, Nível 2, Petróleo e Gás); ITUB4 R$ 48,35 (PN, Nível 1, Bancos); VALE3 R$ 66,42 (ON, Novo Mercado); TAEE11 = Unit |
| TD-08 | P/VP dos FII | `p_vp` de KNCR11 e HGLG11 | perto de 1 | 1,02 e 0,94; 288 de 334 FII com P/VP |
| TD-09 | Regras de qualidade da gold | `control.data_quality_results` do `gold_b3` | CRITICAL passam | `fct_cotacao_chave_unica` e `dim_ativo_chave_unica` PASSED; as INFO (`eventos_detetados`, `retorno_diario_extremo`, `acao_sem_emissor`) registadas para revisão |

---

## Painel (página Bolsa)

| ID | Caso | Esperado | Obtido |
|---|---|---|---|
| TP-01 | Indicadores no topo | BOVA11, variação no ano, nº de ações, volume médio | R$ 201,39 (−1,11 % no dia); +27,5 % no ano; 358 ações (71 altas, 228 baixas); R$ 32,6 bi/dia |
| TP-02 | Rankings com a classe Ações | 6 cartões alinhados, ticker + nome cortado + valor + barra | ok (altas e baixas do dia, mais negociados, 12 meses, ano) |
| TP-03 | Classe FII | ranking "Menor P/VP" no lugar de "altas no ano" | ok (TGAR11 0,47; BRCR11 0,57) |
| TP-04 | Evolução base 100 e setores | 4 papéis por omissão; seletor de período; barras por setor | ok depois de corrigir o rótulo "BOVA11 · nan" e a largura do seletor |
| TP-05 | App publicada | `https://findata-depoussis.streamlit.app/acoes` com o snapshot novo | ok depois do push |

---

## Defeitos encontrados e corrigidos

| ID | Defeito | Causa | Correção |
|---|---|---|---|
| D-01 | Primeiro backfill falhou: `HTTP 403` em `COTAHIST_A2021.ZIP` (run `720093533286858`) | User-Agent com acento ("públicos"); a Cloudflare da B3 rejeita cabeçalhos não ASCII. O mesmo pedido sem acento dava 200 | `config/sources/bcb.yaml`: User-Agent só ASCII |
| D-02 | Contagens do Auto Loader e do CDF a 0 com dados carregados (run `580474600144089`) | no serverless (Spark Connect) o `foreachBatch` corre noutro processo: variáveis do notebook alteradas lá dentro não voltam | contagens lidas depois, no registo de ficheiros, na bronze e no `DESCRIBE HISTORY` da gold |
| D-03 | Tarefa `gold_b3` falhou depois de aplicar as alterações (run `492130559376852`) | o progresso do stream no Spark Connect traz `numInputRows = None` | métrica removida; os dados não foram afetados (TF-11 deu 0 diferenças) |

Na TF-11 apareceram dois problemas no próprio teste, ambos corrigidos:
- A consulta foi achatada numa só linha e os comentários `--` anularam o resto do SQL.
- Uma divisão por zero na comparação: há fechos a 0. Passou a usar diferença absoluta relativa ao valor esperado.

---

# Parte 2: fundamentos, proventos e modelo preditivo

Testes de 16/10/2026 sobre as fontes novas (DFP/ITR da CVM e proventos da B3), a substituição da heurística pelos
eventos oficiais e o modelo de ranking. Documentação funcional em [fundamentos.md](fundamentos.md) e
[modelo_preditivo.md](modelo_preditivo.md).

Resumo: **9 TU, 1 TI (repetido), 9 TF, 10 TD e 4 TP, todos aprovados no fim**. Os defeitos D-04 a D-07,
encontrados e corrigidos durante os testes, estão no fim.

## Testes unitários

```bash
.venv/Scripts/python -m pytest tests/unit/test_b3.py tests/unit/test_ml.py -v   # suite completa: 65 aprovados
```

| ID | Teste | Verifica | Estado |
|---|---|---|---|
| TU-10 | `test_proventos_urls_numeros_e_datas` | parâmetros da API em JSON base64; números brasileiros (`0,674`, `1.234,5`); datas `dd/mm/aaaa` (inclui `31/12/9999`); chaves em falta; nº de páginas | aprovado |
| TU-11 | `test_registo_de_provento_para_a_bronze` | um provento real da API vira as colunas da bronze; campos novos da API são ignorados | aprovado |
| TU-12 | `test_regras_de_contas_dos_fundamentos` | o SQL dos fundamentos não tem chavetas soltas (passa por `str.format`); as regras de descrição apanham "Lucro/Prejuízo Consolidado do Período", "Lucro ou Prejuízo Líquido do Exercício", "Atribuído a Sócios da Empresa Controladora", PL, não controladores, caixa e aplicações; não apanham "Lucro por Ação" nem "Não Controladores" como controladora | aprovado |
| TU-09 (revisto) | `test_calculo_gold_reutilizado_pela_carga_incremental_e_pela_verificacao` | além do anterior: eventos oficiais têm prioridade sobre a heurística; fórmulas do fator (% e fração) | aprovado |
| TU-13 | `test_dobras_nunca_treinam_com_o_mes_de_teste_nem_o_anterior` | walk-forward: o treino de cada mês acaba pelo menos ~40 dias antes do mês de teste; mínimo de 18 meses | aprovado |
| TU-14 | `test_alvo_acima_da_mediana_por_data_e_nan_sem_futuro` | alvo por data (mediana da própria data); sem retorno futuro → sem alvo | aprovado |
| TU-15 | `test_ranks_por_data` | percentis calculados só entre as ações da mesma data | aprovado |
| TU-16 | `test_auc_e_ic` | AUC pela fórmula de Mann-Whitney (1, 0 e 0,5 em casos conhecidos); IC de Spearman | aprovado |
| TU-17 | `test_carteira_com_custos_e_rotacao` | carteira top N: custo de entrada (1 lado), rotação, custo de 2 lados e comparação com o universo | aprovado |
| TU-18 | `test_sql_das_features_point_in_time` | o SQL das features tem as três salvaguardas (fundamentos ≤ t, dividendos com data ex ≤ t, alvo 21 pregões à frente) e todas as variáveis do modelo | aprovado |

## Teste de integração

| ID | TI-01 (repetido com eventos oficiais) |
|---|---|
| Objetivo | Depois de trocar a heurística pelos eventos oficiais, a gold incremental continua igual a uma reconstrução completa |
| Como | `sql_diferencas(k)` compara também `fator_evento` com tolerância relativa |
| Obtido | tarefa `testes_integracao` SUCCESS |
| Evidência | run `160388811525714` |

## Testes funcionais

| ID | Caso | Passos | Esperado | Obtido | Evidência |
|---|---|---|---|---|---|
| TF-12 | Backfill DFP/ITR 2021-2026 | job CVM, `run_mode=backfill`, `entidades=cia_aberta_dfp,cia_aberta_itr`, só as tarefas bronze, silver e `gold_fundamentos` | 12 ZIP `PROCESSED`; silver com contas e documentos | bronze e silver SUCCESS (DRE da DFP: 401 460 linhas); a gold falhou (D-04) | run `475095205445948` |
| TF-13 | Gold de fundamentos | só a tarefa `gold_fundamentos` | uma linha por companhia e trimestre | 1.ª tentativa: regra CRITICAL de chave única falhou (D-05); depois da correção, SUCCESS: 15 536 trimestres de 878 companhias | runs `802234466502566` (falhou), `1010774919313167` |
| TF-14 | Primeira carga de proventos | job `findata_dev_b3_proventos` | empresas ativas, sem falhas; silver e gold | 310 empresas, 725 pedidos, 0 falhas; 18 536 proventos, 716 eventos, 310 empresas; `fct_provento` 17 175 linhas em 358 tickers (17 118 com data ex) | run `987355423546317` |
| TF-15 | Gold da B3 reconstruída com eventos oficiais | só `gold_b3`, `run_mode=reprocess` | reconstrução e checkpoints dos dois streams reiniciados | SUCCESS | run `504488120425256` |
| TF-16 | Proventos recalculados com os novos fatores | só `gold_b3_proventos` | `valor_ajustado` com os fatores oficiais | SUCCESS | run `997666706312965` |
| TF-17 | Features do modelo | job `findata_dev_ml`, tarefa `ml_features` | regras CRITICAL anti-futuro com 0 falhas | 12 594 linhas (413 ações, 58 datas); `ml_fundamentos_publicados_antes` 0/12 594; `ml_alvo_depois_da_referencia` 0/12 594; chave única OK | run `188558971629497` |
| TF-18 | Treino, backtest e registo | tarefa `ml_treino` | 3 modelos, 37 meses fora da amostra, MLflow, modelo no Unity Catalog, 5 tabelas gold | SUCCESS; MLflow run `7722ad9d1115465f875e127bff38ec0d`; modelo `findata_dev.gold.ranking_acoes` v1 | run `188558971629497` |
| TF-19 | Pipeline semanal do ADF | `pl_findata_semanal` com `B3 proventos → Modelo` em paralelo com a auditoria | publicado com `job_id_b3_proventos` e `job_id_ml` | teste unitário `test_adf.py` aprovado | — |
| TF-20 | SQL validado antes de correr | `EXPLAIN` no warehouse dos SQL de fundamentos, features e cotações | sem erros de sintaxe ou análise | os três OK (depois de D-04) | — |

## Validação de dados

| ID | Caso | Esperado | Obtido |
|---|---|---|---|
| TD-10 | Lucro 12 meses e PL contra os balanços publicados | valores dos relatórios anuais | Petrobras 2025: lucro R$ 110,1 bi, PL R$ 415,8 bi, dívida R$ 384 bi; WEG 2025: R$ 6,4 bi; Itaú 2025: R$ 44,9 bi |
| TD-11 | Código de contas diferente por setor | lucro e PL identificados em indústria, banco e seguradora | Itaú (3.09/2.08), BB Seguridade (3.13/2.03) e WEG/Petrobras (3.11/2.03) |
| TD-12 | Número de ações da CVM | ações em unidades | **Itaú declara em milhares** (10,8 mi vs 11,03 mil mi na B3) → valor de mercado passou a usar a B3 (D-07) |
| TD-13 | Número de ações da B3 | coerente com o mercado | PETR 7,44 mil mi ON + 5,45 mil mi PN; ITUB 11,03 mil mi; VALE 4,44 mil mi |
| TD-14 | DY por ano | coerente com a história | PETR4 49,9 % (2022) e 24,7 % (2023); TAEE11 8–10 %/ano; DY 12m ITUB4 7,6 %, VALE3 7,7 % |
| TD-15 | Proventos sem ticker | só espécies sem papel líquido | 15 de 449 combinações emissor/espécie (ex.: CEEB PNB, BRBI ON/PN), regra INFO `provento_sem_ticker` |
| TD-16 | Yield de evento acima de 30 % | rever | 9 casos (ex.: CEBR5 31 % em 2021, CASH3 2024), regra INFO `yield_evento_suspeito` |
| TD-17 | Heurística contra eventos oficiais | eventos detetados | **38 de 105** desdobramentos/grupamentos desde 2021 não detetados e nenhuma bonificação (D-06). Ex.: VAMO3 1:4 (razão 0,228, fora da tolerância), CMIG4 +30 % (−23 % no preço), EGIE3 +40 %, ITUB4 +3 %, BBDC4 +10 % |
| TD-18 | Cobertura de fundamentos nas features | maioria das linhas | 9 930 de 12 594 com lucro/valor de mercado (2 664 sem fundamentos: empresas sem DFP/ITR ligadas ao ticker ou meses iniciais) |
| TD-19 | Resultados do backtest plausíveis | AUC entre 0,5 e ~0,6 (mais alto seria suspeito) | AUC 0,523 / 0,568 / 0,556; IC 0,04 / 0,13 / 0,11 |

## Painel

| ID | Caso | Obtido |
|---|---|---|
| TP-06 | Navegação no topo (pedido do utilizador) | Mercado, Bolsa e Modelo como abas; menus "Fundos" (3 páginas) e "Plataforma"; faixa com data do snapshot e fontes por baixo |
| TP-07 | Página Modelo | indicadores (AUC 0,556, IC 0,109, carteira +46,6 %, 37 meses), backtest com escolha do modelo, comparação, IC por mês, importância das variáveis, ranking atual; a tabela de comparação foi reduzida a 5 colunas, porque cortava |
| TP-08 | Bolsa: dividendos | cartão "Dividendos e JCP por ano" (PETR4: barras por ano e tabela com DY) |
| TP-09 | Bolsa: indicadores | colunas DY 12m, P/L, P/VP e ROE nas ações; ranking "Maior dividend yield (12 meses)" |

## Defeitos encontrados e corrigidos (parte 2)

| ID | Defeito | Causa | Correção |
|---|---|---|---|
| D-04 | `gold_fundamentos`: `PARSE_SYNTAX_ERROR` | o Spark SQL não aceita uma moldura sobre uma janela com nome (`OVER (w ROWS BETWEEN ...)`), confirmado no warehouse | janelas escritas por extenso nos fundamentos e nas features; os SQL passaram a ser validados com `EXPLAIN` antes de correr |
| D-05 | Chave única falhou na gold de fundamentos (8 trimestres repetidos) | algumas empresas entregam uma ITR também do 4.º trimestre, além da DFP | fica a DFP (`QUALIFY` por documento) |
| D-06 | Bonificações e vários desdobramentos sem ajuste no preço (TD-17) | a heurística só procura fatores inteiros com tolerância de 8 % | eventos oficiais da B3 nas ações cobertas; heurística só em FII/ETF; gold reconstruída |
| D-07 | Valor de mercado errado para empresas que declaram ações em milhares | unidade inconsistente na composição do capital da CVM | valor de mercado = preço ajustado × nº de ações da B3 (mesma base de ações) |

O teste unitário TU-17 também tinha uma expectativa errada. A carteira do 2.º mês (1,8 %) rendia menos do que o
universo (2,33 %), por isso a percentagem de meses acima do universo é 50 % e não 100 %. Foi corrigido o teste,
não o código.

---

# Parte 3: simulador de investimento

Ver [simulador.md](simulador.md). Testes de 16/10/2026.

| ID | Tipo | Caso | Resultado |
|---|---|---|---|
| TU-19 | unitário | `test_compra_ao_preco_da_epoca_quantidade_inteira_e_sobra`: compra num dia sem pregão usa o seguinte; 1 005 a 10,00 → 100 ações e 5 de sobra | aprovado |
| TU-20 | unitário | `test_desdobramento_duplica_as_acoes_sem_mudar_o_patrimonio`: fator 0,5 → 100 → 200 ações; descrições de grupamento e bonificação (10 % e 30 %) | aprovado |
| TU-21 | unitário | `test_proventos_pela_posicao_na_data_com_com_ir_do_jcp`: dividendo com 100 ações; JCP depois do desdobramento com 200 ações e 15 % de IR; sem IR = 200 | aprovado |
| TU-22 | unitário | `test_compra_depois_da_data_com_nao_recebe_e_reinvestimento_compra_no_pregao_seguinte`: provento anterior à compra ignorado; reinvestido ao fecho do pregão seguinte | aprovado |
| TU-23 | unitário | `test_valorizacao_mais_proventos_igual_ao_ganho_total`: com e sem reinvestimento | aprovado |
| TD-20 | dados | Rendimentos de FII estimados pela CVM contra a B3 (KNCR11, HGLG11) | diferença < 1 %; datas com iguais |
| TD-21 | dados | `fct_provento` com FII | 15 415 rendimentos de 422 FII; DY 12m KNCR11 11,8 %, MXRF11 10,8 %, HGLG11 7,8 % |
| TF-21 | pipeline | `gold_b3_proventos` com os rendimentos de FII (run `864337872529095`) | SUCCESS |
| TP-10 | painel | PETR4 desde 02/05/2023 | 439 ações a R$ 22,74; +152 % de valorização, R$ 6 540 de proventos, +217,8 % no total |
| TP-11 | painel | CMIG4 (evento) | bonificação de 30 % em 30/04/2024 listada; quantidade 1 051,70; 19 pagamentos com a quantidade de cada data |
| TP-12 | painel | KNCR11 (FII) | 105 cotas; +10,8 % de valorização + 46,5 % em rendimentos = +57,3 % (Selic +51,1 %) |
| TP-13 | painel | Descrição dos eventos | o texto longo cortava as colunas Antes/Depois; encurtado para "Bonificação de 30 %", "Desdobramento 1:2" |

| TU-24 | unitário | `test_imposto_na_venda_por_classe_isencao_e_prejuizo`: ações 15 % (PETR4 do exemplo), isenção até R$ 20 mil e sem ela, FII 20 % sem isenção, ETF com prejuízo = 0 | aprovado |
| TU-25 | unitário | `test_reinvestimento_entra_no_custo_de_aquisicao`: 500 reinvestidos → custo 1 500 | aprovado |
| TU-26 | unitário | `test_selic_liquida_pela_tabela_regressiva`: 22,5 % / 17,5 % / 15 % pelo prazo | aprovado |
| TP-14 | painel | Resumo com IR, PETR4 | total bruto R$ 31 720,58; IR R$ 2 279,73; **total líquido R$ 29 440,85**; Selic líquida +43,4 % |
| TP-15 | painel | Resumo com IR, KNCR11 | IR de 20 % = R$ 215,25; **total líquido R$ 15 452,67**; opção de isenção desativada (só ações) |
| TP-16 | painel | Formato dos valores | a tabela mostrava 9982.86; passou ao formato brasileiro (R$ 9.982,86 e 100,0 %) |

Total da suite unitária: **73 testes aprovados**.
