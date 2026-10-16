# Conceitos usados na plataforma

Explicação curta de cada técnica, com o sítio do projeto onde está aplicada e o caso de teste que a demonstra
([testes.md](testes.md)).

## Arquitetura medalhão (bronze, silver, gold)

Os dados passam por três camadas, cada uma com uma responsabilidade:

| Camada | Pergunta a que responde | No projeto |
|---|---|---|
| **Bronze** | "O que é que a fonte enviou?" | texto como recebido, mais colunas de auditoria (`_source_url`, `_file_hash`, `_pipeline_run_id`...). Nada é corrigido nem apagado |
| **Silver** | "Qual é o valor certo de cada registo?" | tipos corretos, uma linha por chave, quarentena do que não converte, histórico (SCD) |
| **Gold** | "O que é que o negócio quer ver?" | modelo dimensional (`dim_*`, `fct_*`) e vistas (`vw_*`) para o painel |

Separar as camadas permite reprocessar a silver e a gold a partir da bronze sem voltar à fonte, e auditar qualquer
número até ao ficheiro original, guardado no volume `ops.raw`.

## Delta Lake

Formato de tabela sobre ficheiros Parquet, com um **log de transações** (`_delta_log`). Cada escrita é um commit
numerado (versão 0, 1, 2...). Daí vem tudo o que se segue.

| Capacidade | O que significa | No projeto |
|---|---|---|
| **Transações ACID** | uma escrita entra toda ou não entra; quem lê nunca vê metade | uma carga da bronze que falha a meio não deixa linhas soltas |
| **MERGE** | inserir, atualizar ou apagar numa só operação, casando por chave | SCD1/SCD2 da silver (`src/scd/merge_sql.py`) e a gold incremental da B3 |
| **Histórico e time travel** | `DESCRIBE HISTORY` lista os commits; `VERSION AS OF n` lê a tabela como estava | as contagens do stream da gold vêm do histórico (TF-08 a TF-10) |
| **Change Data Feed (CDF)** | a tabela guarda o que mudou em cada versão: `insert`, `update_preimage`/`update_postimage`, `delete` | ligado na silver (`delta.enableChangeDataFeed`); alimenta a gold da B3 e as reapresentações (`audit/reapresentacoes`) |
| **Esquema imposto** | escrever colunas que não existem ou com outro tipo falha | a bronze só aceita as colunas do contrato; um cabeçalho novo vai para a quarentena |
| **`INSERT ... REPLACE WHERE`** | substitui só as linhas de um intervalo, atomicamente | `fct_fundo_diario` da CVM (meses alterados) |
| **Liquid clustering** (`CLUSTER BY`) | organiza os ficheiros pelas colunas mais filtradas, para ler menos dados | `CLUSTER BY (data_pregao, ticker)` nas cotações |
| **Escrita idempotente** (`txnAppId` + `txnVersion`) | o Delta guarda o último `txnVersion` de cada aplicação; uma escrita repetida com a mesma versão é ignorada | lotes do Auto Loader na bronze da B3 |

## Unity Catalog e volumes

O Unity Catalog é o catálogo que governa tabelas e ficheiros: nomes em três níveis (`findata_dev.silver.tabela`),
permissões (`GRANT`) e linhagem. Os **volumes** guardam ficheiros que não são tabelas, como pastas com permissões:
- `ops.raw`: originais imutáveis;
- `ops.quarantine`: ficheiros e registos rejeitados;
- `ops.checkpoints`: estado dos streams.

## Structured Streaming

O Spark trata uma fonte que cresce (ficheiros numa pasta, alterações de uma tabela) como uma tabela infinita. Cada
**micro-lote** processa só o que chegou desde o anterior.

- **Checkpoint:** pasta onde o stream regista o que já processou (ficheiros lidos, versões do Delta) e o lote em
  curso. Se a execução falhar, recomeça do último lote confirmado, sem perder nem repetir. No projeto:
  `/Volumes/findata_dev/ops/checkpoints/bronze_b3_cotahist` e `.../gold_b3_fct_cotacao`.
- **`trigger(availableNow=True)`:** em vez de ficar ligado à espera de dados (caro), processa tudo o que está
  disponível, em um ou mais lotes, e termina. É "streaming em batch": a garantia de processar cada dado uma vez, com
  o custo de um job agendado. É o único modo de stream no compute serverless.
- **`foreachBatch`:** dá cada micro-lote como um DataFrame normal, para fazer o que o stream não faz sozinho, como
  `MERGE`, várias escritas ou junções com tabelas de controlo. No serverless (Spark Connect) corre noutro processo:
  não pode alterar variáveis do notebook (defeito D-02 em [testes.md](testes.md)).
- **Exactly-once:** checkpoint + escrita idempotente. Se um lote falhar depois de escrever mas antes de confirmar o
  checkpoint, é repetido, e o `txnVersion` impede a duplicação.

## Auto Loader

Fonte de streaming do Databricks (`format("cloudFiles")`) que vigia uma pasta e entrega **só os ficheiros novos**.
Guarda no checkpoint a lista dos ficheiros já vistos, por isso não é preciso compará-los à mão.

| Opção | Para quê | No projeto |
|---|---|---|
| `cloudFiles.format` | formato dos ficheiros | `csv` com uma só coluna `linha` (o TXT da B3 é de largura fixa) |
| `pathGlobFilter` | que ficheiros considerar | `*.TXT`: o ZIP e o ficheiro temporário `.parcial` são ignorados |
| `cloudFiles.includeExistingFiles` | ler ou não o que já estava na pasta no primeiro arranque | `false` na migração (esses TXT já estavam na bronze), `true` num ambiente novo |
| `_metadata.file_path` | caminho do ficheiro de cada linha | liga o TXT ao seu registo `RECEIVED` |

Padrão usado: o download escreve com nome temporário e só renomeia para `*.TXT` depois de validar e registar. Assim
o Auto Loader nunca lê um ficheiro a meio (TF-06).

## Watermark: dois significados

A palavra aparece com dois sentidos diferentes. No projeto usa-se o primeiro.

**1. Watermark de ingestão (marca d'água de controlo)**, em `control.ingestion_watermark`: a última data de
referência confirmada de cada entidade (ex.: último pregão da B3 na silver, `2026-10-15`).
- Só é confirmado pela silver, depois das regras de qualidade, e **nunca recua**: uma carga com dados mais antigos
  não o faz voltar atrás (verificado nos testes de integração, "watermark não recua").
- Serve para saber até onde os dados estão completos e para o controlo de atraso (`audit/frescura`): se o
  watermark tiver mais de N dias (`config/sla.yaml`, 5 para a B3), a execução falha e o ADF dispara o alerta.
- A carga incremental não confia cegamente nele: revê uma **janela** para trás (10 dias na B3, 12 meses na CVM),
  porque as fontes republicam dados antigos.

**2. Watermark de streaming (event time)**, em `withWatermark("evento_ts", "10 minutes")`: diz ao Spark até que
ponto pode esperar por eventos atrasados numa agregação por janelas de tempo (ex.: candles de 1 minuto). Eventos
mais atrasados do que o limite são descartados, e o estado das janelas antigas é libertado da memória.
**Não é usado aqui**: as cotações chegam por ficheiros diários completos, sem eventos fora de ordem. Seria
necessário num stream de eventos ao vivo, como a ideia do "pregão simulado" com Event Hubs.

## Deduplicação: em que camada e como

A mesma informação pode chegar várias vezes: um ficheiro republicado, o mesmo pregão no anual e no diário, uma
execução repetida. A plataforma trata isso em cada nível:

| Nível | Técnica | Exemplo |
|---|---|---|
| Ficheiro (antes de descarregar) | `HEAD` compara ETag/Last-Modified com a última versão registada | diário já carregado → `SEM_ALTERACAO`, sem download |
| Ficheiro (depois de descarregar) | sha256 do conteúdo contra os hashes já processados | conteúdo igual a uma versão anterior → `DUPLICATE` |
| Lote de streaming | checkpoint + `txnAppId`/`txnVersion` | lote repetido depois de uma falha não duplica a bronze |
| Registo (silver) | `QUALIFY row_number() OVER (PARTITION BY chave ORDER BY _ingestion_timestamp DESC) = 1` | o pregão que chega no anual e no diário fica uma vez, a carga mais recente (TF-03) |
| Registo (silver) | `record_hash` no `MERGE`: só escreve se o hash mudou | reprocessar dados iguais dá 0 alterações |
| Verificação | regra CRITICAL `chave_unica` | falha a execução se a chave aparecer duas vezes |

A **bronze não é deduplicada de propósito**: guarda tudo o que foi recebido, para auditoria. Por isso o pregão de
15/10 aparece lá três vezes (anual, diário e o teste TF-06), mas na silver e na gold só uma.

## SCD1 e SCD2 (dimensões que mudam)

- **SCD1:** guarda só o valor atual. Se o valor muda, sobrescreve. Ex.: cotações, informes, `cvm_valor_mobiliario`.
  A silver tem `_inserted_at`, `_updated_at` e o CDF regista as alterações (reapresentações).
- **SCD2:** guarda o histórico. Quando um atributo muda, a versão atual é fechada (`valid_to`,
  `is_current = false`) e entra uma nova. Ex.: cadastro de fundos e de companhias. Responde a perguntas como "qual
  era o administrador deste fundo em março?".

## Idempotência e reprocessamento

Uma execução é **idempotente** quando repeti-la dá o mesmo resultado. Os pipelines garantem-no assim:
- o MERGE por chave na silver e na gold;
- o `INSERT OVERWRITE` nas dimensões;
- o registo de ficheiros por hash;
- a escrita transacional no stream.

Os modos de execução (`run_mode`) são:

| Modo | O que faz |
|---|---|
| `incremental` | só o novo e a janela de revisão |
| `backfill` | todo o histórico desde `inicio_backfill` |
| `reprocess` | volta a descarregar um intervalo; na gold da B3 reconstrói tudo e reinicia o checkpoint do CDF |

## Qualidade de dados e quarentena

Cada regra é uma consulta que devolve os registos inválidos (`src/quality/rules.py`), gravada em
`control.data_quality_results` com uma amostra. As severidades são:
- **CRITICAL:** bloqueia a publicação na gold e o avanço do watermark;
- **HIGH:** regista e bloqueia a gold;
- **INFO:** só regista, para revisão (ex.: eventos detetados, ações sem emissor).

Registos que não convertem vão para a quarentena (`ops.quarantine`) com o motivo, em vez de serem descartados em
silêncio.
