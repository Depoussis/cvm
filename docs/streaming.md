# Streaming na plataforma (B3)

Dois padrões de Structured Streaming aplicados à carga da B3, sem infraestrutura nova: nada fica ligado, cada stream
corre com `trigger(availableNow=True)` dentro do job diário. Processa tudo o que é novo desde a última execução e
termina, e o checkpoint guarda onde parou.

```text
download (HTTP) ──► raw/…/NOME.ZIP + extraidos/NOME.TXT ──► registo RECEIVED
                                                │
                    Auto Loader (cloudFiles) ◄──┘   checkpoint: ops/checkpoints/bronze_b3_cotahist
                                                │
                                                ▼
                         bronze.b3_cotahist ──► silver.b3_cotacao_diaria (SCD1, Change Data Feed ligado)
                                                │
                    readChangeFeed (stream) ◄───┘   checkpoint: ops/checkpoints/gold_b3_fct_cotacao
                                                │
                                                ▼
                                  gold.fct_cotacao_diaria (só os tickers alterados)
```

## 1. Bronze com Auto Loader (`notebooks/bronze/b3.py`)

O download deixa de escrever na bronze. Para cada ficheiro, guarda o ZIP no volume raw, extrai o TXT e valida o
cabeçalho e o trailer, lendo o ficheiro em fluxo. Se o ficheiro estiver completo, regista-o como `RECEIVED` em
`control.source_file_registry`. O TXT é escrito com um nome temporário e só ganha o nome final depois do registo,
para o Auto Loader nunca ler um ficheiro a meio.

O Auto Loader (`cloudFiles`, formato csv com uma coluna `linha`) vigia `ops/raw/b3/cotahist/`. Em cada lote
(`foreachBatch`) faz o seguinte:
1. junta cada TXT ao seu registo `RECEIVED`, pela pasta da execução e pelo nome sem extensão
   (`src/ingestion/b3/cotahist.py: chave_ficheiro`, testado);
2. escreve na bronze os registos do mercado à vista, com `txnAppId`/`txnVersion`. Se um lote for repetido depois de
   uma falha, o Delta reconhece a transação e não duplica linhas;
3. marca os ficheiros `PROCESSED`.

O stream corre **duas vezes** por execução: no início, para apanhar ficheiros `RECEIVED` de uma execução que falhou
a meio, e depois dos downloads. Se no fim sobrar algum ficheiro `RECEIVED`, a execução falha.

**Migração:** numa bronze que já tinha dados (carregados pelo método anterior), a primeira execução usa
`cloudFiles.includeExistingFiles = false`, porque esses TXT já estão na bronze. Num ambiente novo, lê tudo.

## 2. Gold incremental com Change Data Feed (`notebooks/gold/b3.py`)

A silver `b3_cotacao_diaria` tem `delta.enableChangeDataFeed = true`. A gold lê as alterações em stream
(`readChangeFeed`). Para cada lote:
1. **d0** = primeira data inserida ou alterada de cada ticker. O cálculo (`src/gold/cotacoes.py: calculo`, o mesmo
   da reconstrução completa) corre desde o pregão anterior a d0 até ao fim da série desse ticker;
2. o preço ajustado dos pregões **antes** de d0 é multiplicado por `fator_novo / fator_antigo`, o produto dos
   fatores de evento no intervalo recalculado, depois e antes. Assim, um desdobramento novo reajusta o passado sem
   recalcular a série inteira;
3. `MERGE` das linhas recalculadas. Basta inserir ou atualizar, porque a silver é SCD1 e nunca apaga.

Num dia normal entra um pregão novo por ticker: o lote recalcula uma linha por ticker em vez de 1,27 M. Na primeira
execução, sem checkpoint, o CDF entrega a silver inteira como inserts, o que equivale a uma reconstrução. Com
`run_mode=reprocess`, a gold é reconstruída de raiz e o checkpoint recomeça em `startingVersion = latest`.

**Contagens:** no serverless (Spark Connect), o `foreachBatch` corre noutro processo. Variáveis do notebook
alteradas lá dentro não voltam, e o progresso do stream não traz `numInputRows`. Por isso as contagens de cada
execução são lidas depois:
- bronze: no registo de ficheiros e na própria bronze;
- gold: no `DESCRIBE HISTORY` da tabela (métricas dos `MERGE`).

Ficam em `control.pipeline_execution.parameters`.

### Segundo stream: eventos oficiais da B3

Desde a integração dos proventos ([fundamentos.md](fundamentos.md)), o fator de evento das ações vem de
`silver.b3_evento_acao`, que é carregada semanalmente e também tem CDF. Um segundo stream na mesma tarefa
(`aplicar_eventos`, checkpoint `ops/checkpoints/gold_b3_eventos_oficiais`) faz o seguinte:
1. lê os eventos novos ou alterados;
2. liga-os ao ticker pelo ISIN;
3. recalcula esses tickers a partir da data com, com a mesma função `recalcular` do stream de cotações.

Assim, um desdobramento ou bonificação publicado na carga de domingo reajusta o histórico do papel na execução
seguinte, sem reconstruir a tabela. Em `reprocess`, os dois checkpoints são apagados e recomeçam em
`startingVersion = latest`, depois da reconstrução completa.

## Como foi verificado

Os casos de teste (Auto Loader TF-06/07, CDF TF-08 a TF-11, integração TI-01), com passos, resultados e IDs das
execuções, estão em [testes.md](testes.md). Os conceitos (checkpoint, `availableNow`, `foreachBatch`, idempotência,
watermark, deduplicação) estão explicados em [conceitos.md](conceitos.md).

## Próximos passos possíveis

- Silver em stream a partir da bronze (append-only), com a quarentena e as regras de qualidade no `foreachBatch`.
- O mesmo padrão de CDF para as gold da CVM (`fct_fundo_diario` ainda substitui intervalos por mês).
- Uma fonte em tempo real verdadeira (ver as ideias de pregão simulado com Event Hubs e cripto por WebSocket).
