# Modelo preditivo: ranking de ações (experimental)

> Projeto de estudo. Não é recomendação de investimento. O objetivo é construir e avaliar com honestidade um
> processo de machine learning sobre a plataforma, não prometer retornos.

## Pergunta

*Esta ação vai render mais do que a mediana das ações líquidas nos próximos 21 pregões (~1 mês)?*

O modelo devolve uma probabilidade por ação e o resultado é uma **ordenação**. Isto é mais robusto do que tentar
acertar o preço, e é o que interessa para escolher uma carteira.

## Dados e variáveis (`src/ml/features.py` → `gold.ml_features`)

Uma linha por ação e **data de referência** (último pregão de cada mês, mais o último disponível). São 12 594
linhas: 413 ações e 58 datas, de 2022-01 a 2026-10. O universo são as ações em lote padrão com volume médio
≥ R$ 1 mi/dia nos 21 pregões anteriores e mais de 252 pregões de histórico (~180 por mês).

| Grupo | Variáveis | Fonte |
|---|---|---|
| Preço | retorno 1, 3 e 6 meses; momentum 12-1; volatilidade 3 meses; distância à máxima de 52 semanas | `fct_cotacao_diaria` (preço ajustado) |
| Liquidez e tamanho | volume médio (log); valor de mercado (log) | cotações + nº de ações da B3 |
| Dividendos | dividend yield 12 meses (proventos com data ex até t) | `fct_provento` |
| Fundamentos | lucro/valor de mercado; PL/valor de mercado; ROE; margem líquida; dívida líquida/PL | `fct_fundamentos_trimestre` |
| Macro | Selic meta, variação da Selic em 3 meses, dólar em 1 mês | BCB (SGS 432, PTAX) |
| Setor | setor de atividade (categórica) | cadastro CVM |

As variáveis por ação entram no modelo como **percentil entre as ações da mesma data**. Isso tira o nível do
mercado e o efeito dos outliers.

**Valor de mercado** = preço ajustado em t × número de ações atual da B3. As duas grandezas estão na base de ações
de hoje, por isso o produto é o valor de mercado em t, sem depender do número de ações declarado à CVM (o Itaú
declara-o em milhares). Units ficam sem valor de mercado.

**Alvo:** retorno total nos 21 pregões seguintes, ou seja preço ajustado + dividendos com data ex na janela.
Vale 1 se ficar acima da mediana das ações nessa data.

## Sem olhar para o futuro

| Regra | Como | Verificação |
|---|---|---|
| Fundamentos só depois de públicos | `data_publicacao` (entrega à CVM) ≤ t; trimestre no máximo 15 meses antes | regra CRITICAL `ml_fundamentos_publicados_antes` (0 falhas) |
| Dividendos só depois da data ex | `data_ex` ≤ t | teste unitário do SQL |
| Alvo estritamente no futuro | 21 pregões depois de t | regra CRITICAL `ml_alvo_depois_da_referencia` (0 falhas) |
| Treino só com o passado já conhecido | walk-forward com um mês de intervalo | teste unitário `test_dobras_nunca_treinam_com_o_mes_de_teste_nem_o_anterior` |
| Preços comparáveis no tempo | preço ajustado a desdobramentos, grupamentos e bonificações oficiais | [fundamentos.md](fundamentos.md) |

## Validação walk-forward e backtest (`src/ml/avaliacao.py`, `notebooks/ml/treino.py`)

Para cada mês de teste m, de 2023-08 a 2026-08 (**37 meses fora da amostra**):
1. treina com todos os meses até m−2 (pelo menos 18). O mês m−1 fica de fora porque o seu alvo pode terminar uns
   dias depois de m;
2. pontua as ações de m;
3. monta uma carteira igual-ponderada com as **10 maiores pontuações**, mantida até ao mês seguinte. Os custos
   são 0,10 % por lado sobre a parte da carteira que muda.

Há três modelos comparados nas mesmas condições:
- **momentum 12-1:** referência sem machine learning;
- **regressão logística:** variáveis padronizadas;
- **gradient boosting:** `HistGradientBoostingClassifier`, 200 árvores, 15 folhas, mínimo de 100 exemplos por
  folha, setor categórico.

### Resultados (execução de 17/10/2026, modelo v2)

Retreinado depois da [validação contra fontes externas](validacao_dados.md). A validação corrigiu três erros nos
dados da B3:
- 17 bonificações que apareciam como quedas de 4 a 23 %;
- proventos em falta de 9 emissores;
- parcelas de proventos perdidas.

| Modelo | AUC média | IC médio | t do IC | IC > 0 | Carteira top 10 | Ao ano | Volatilidade | Queda máx. |
|---|---|---|---|---|---|---|---|---|
| Momentum 12-1 | 0,526 | +0,044 | 2,11 | 65 % | −34,0 % | −12,6 % | 27,3 % | −43,9 % |
| Regressão logística | **0,571** | **+0,136** | 5,43 | 81 % | **+50,2 %** | **+14,1 %** | 13,4 % | −12,0 % |
| Gradient boosting | 0,556 | +0,105 | 5,61 | 95 % | +28,4 % | +8,5 % | 19,7 % | −18,0 % |
| *Universo (média das ações)* | | | | | +11,1 % | | | |
| *BOVA11* | | | | | +47,9 % | | | |

**Comparação com a v1** (16/10, dados ainda com os erros):
- O AUC e o IC quase não mudaram: a capacidade de ordenar as ações mantém-se.
- O retorno da carteira caiu, sobretudo no gradient boosting (+46,6 % → +28,4 %; logística +60,3 % → +50,2 %).
- Parte do resultado da v1 vinha de quedas falsas. Por exemplo, as bonificações anuais da Itaúsa faziam a ação
  parecer barata depois de uma "queda", e o modelo aprendia esse padrão inexistente.
- O ranking de 15/10 já publicado no acompanhamento ao vivo não foi reescrito: é medido tal como saiu.

### Como ler

- **AUC 0,55–0,57:** acima do acaso (0,5) e no intervalo típico de modelos de ações. Um valor muito mais alto
  levantaria a suspeita de fuga de informação.
- **IC médio de 0,10 a 0,14, com t > 5:** a ordenação acerta de forma consistente (em 81–95 % dos meses), não por
  sorte num mês excecional.
- **A carteira bate claramente o universo** (+28 a +50 % contra +11 %). Contra o BOVA11 (+47,9 %) o resultado é
  misto:
  - a logística fica um pouco acima (+50,2 %), com menos volatilidade e uma queda máxima menor;
  - o gradient boosting fica abaixo (+28,4 %).

  Nestes 3 anos as grandes empresas (que pesam no índice) renderam muito mais do que a média das ações líquidas.
- **Momentum sozinho foi mau** neste período (−34,0 %), o que mostra a importância de ter uma referência simples.
- **Variáveis mais importantes** (queda da AUC ao baralhar cada uma, últimos 12 meses fora da amostra): setor,
  dividend yield, momentum 12-1, ROE e dólar. O modelo favoreceu ações defensivas e pagadoras de dividendos
  (energia, telecomunicações, bancos), coerente com um período de juros altos.

### Limitações

- Só ~5 anos de dados, com um único ciclo de juros. O modelo pode estar a aprender esse regime.
- Enviesamento de sobrevivência parcial: ações deslistadas antes de 2021 não entram.
- Restatements: os fundamentos usam a versão mais recente do documento, com a data da primeira entrega.
- Custos e liquidez reais variam; não se modela impacto de mercado.
- O valor de mercado usa o preço de uma classe e o número total de ações (ON + PN).

## Produção

Job **`findata_dev_ml`** (domingo 07:00, pelo ADF `pl_findata_semanal`, depois dos proventos):
`ml_features → ml_treino`. O treino:
- regista tudo no **MLflow**: experimento `/Shared/findata_dev/ml_ranking_acoes`, com parâmetros, métricas por
  modelo, backtest mensal e importância das variáveis;
- regista o modelo final (gradient boosting, treinado com todos os meses rotulados) no **Unity Catalog** como
  `findata_dev.gold.ranking_acoes` (v1 em 16/10/2026).

| Tabela gold | Conteúdo |
|---|---|
| `ml_features` | variáveis e alvo |
| `ml_previsoes` | pontuação fora da amostra por modelo, mês e ação |
| `ml_backtest_mensal` | carteira, universo, BOVA11, rotação, custo, AUC e IC por mês |
| `ml_resumo` | métricas agregadas |
| `ml_importancia` | importância das variáveis por permutação |
| `ml_ranking_atual` | pontuação na data mais recente, com as variáveis que a explicam |
| `ml_ranking_historico` | cada ranking publicado, gravado uma única vez (só inserções) |
| `vw_ml_acompanhamento` | retorno realizado de cada ranking publicado nos 21 pregões seguintes |

## Acompanhamento ao vivo

O backtest é recalculado a cada treino e usa dados que já existiam. Para saber se o modelo funciona **daqui para a
frente**, cada ranking fica gravado quando é publicado e o resultado é medido depois:

1. `ml_treino` faz `MERGE ... WHEN NOT MATCHED INSERT` de `ml_ranking_atual` em `ml_ranking_historico`
   (`sql/facts/47_ml_ranking_historico.sql`). Um ranking já gravado nunca é alterado, mesmo que o job corra de novo
   com a mesma data.
2. `vw_ml_acompanhamento` (`sql/views/73_ml_acompanhamento.sql`) calcula, para cada ação de cada ranking, o retorno
   total nos 21 pregões do próprio papel depois da data do ranking, com **a mesma fórmula do alvo** (preço ajustado
   + proventos ajustados com data ex na janela). Enquanto não passam 21 pregões, mostra o retorno até agora
   (`concluido = false`). Inclui o BOVA11 como referência.
3. A exportação diária do painel leva a view (`ml_acompanhamento`), por isso o resultado anda a cada pregão.
4. `app/painel/modelo_vivo.py` resume cada ranking: top 10 (igual peso) contra o universo e o BOVA11, diferença,
   acerto (fração do top 10 acima da mediana) e IC. O placar junta só os rankings concluídos.

Validação (16/10/2026): aplicada ao mês de 31/08/2026 das previsões do backtest, a view dá o mesmo retorno que
`ml_features.ret_fwd` nas 177 ações (diferença máxima 0).

Primeiro ranking gravado: 15/10/2026 (publicado a 16/10), completo por volta de 14/11/2026. Com um ranking por
semana, os resultados de rankings seguidos sobrepõem-se e não são independentes. São precisos vários meses
concluídos antes de tirar conclusões. Retornos brutos, sem os custos de transação do backtest.

A página **Modelo** do painel Streamlit mostra:
- o acompanhamento ao vivo: placar, resultado de cada ranking e as ações de cada um;
- o backtest, com a escolha do modelo;
- a comparação dos três modelos;
- o IC por mês;
- a importância das variáveis;
- o ranking atual.

A página Bolsa usa as mesmas variáveis para P/L, P/VP e ROE.
