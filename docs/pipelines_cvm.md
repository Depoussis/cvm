# Pipelines da CVM (Fase 3)

Job Databricks **`findata_dev_cvm`** (serverless), criado por `scripts/deploy_workspace.py`:
`bronze_cvm → silver_cvm → gold_cvm`. Agendamento diário às 08:00 de Brasília, criado em pausa.

## Fonte: portal de dados abertos da CVM

Tudo confirmado com pedidos reais em 16/10/2026 (`config/datasets/cvm.yaml`):

| Conjunto | Pacote CKAN | Ficheiro | Notas |
|---|---|---|---|
| Informe diário de fundos | `fi-doc-inf_diario` | `FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_AAAAMM.zip` (1 CSV) | meses desde 2021-01; ~540 mil linhas e 11 MB por mês; 2000–2020 em `DADOS/HIST/` (anuais, ainda não suportado) |
| Cadastro de fundos, classes e subclasses | `fi-cad` | `FI/CAD/DADOS/registro_fundo_classe.zip` (3 CSV) | snapshot completo |
| Cadastro de companhias abertas | `cia_aberta-cad` | `CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv` | snapshot completo |

O catálogo dos pacotes (`package_show`) é guardado em `bronze.cvm_catalogo_recursos` em cada execução.

### O que os dados reais mostraram
- **Schema drift no informe diário:** até 2023 o cabeçalho era `TP_FUNDO;CNPJ_FUNDO;...` (contrato `v1`); com a
  RCVM 175 passou a `TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;ID_SUBCLASSE;...` (`v2`). Os dois estão no contrato; um
  terceiro cabeçalho desconhecido vai para a quarentena e faz a execução falhar.
- **Codificação:** o informe vem em UTF-8 e os cadastros em ISO-8859-1. É detetada por ficheiro e guardada em
  `_source_encoding`.
- **CNPJ em formatos diferentes:** `00.017.024/0001-53` no informe, `00017024000153` nos cadastros. A silver
  normaliza tudo para 14 dígitos.
- **Chaves repetidas nos cadastros:** fundos têm uma linha por gestor (1 058 fundos com vários); companhias uma linha
  por mercado (`TP_MERC`); 4 classes com custodiante/controlador múltiplo. A silver separa gestores numa tabela própria
  e agrega mercados/custodiantes por ordem alfabética, para ter uma linha por chave.
- **Republicação:** a CVM volta a publicar meses recentes (o `Last-Modified` muda). O incremental verifica o ETag dos
  últimos 12 meses e só descarrega o que mudou; conteúdo igual a uma versão já processada fica `DUPLICATE`.
- **Fundo publicado duas vezes no mesmo dia:** na transição para a RCVM 175, 39 583 chaves (CNPJ, subclasse, data)
  de 2024-01 a 2026-07 aparecem duas vezes no mesmo ficheiro, como `FI` e como `CLASSES - FIF` (pico de 13,7 mil em
  2025-06). Em 30 922 os valores são iguais; em **8 661 os valores diferem** (ex.: cota 1,1903 vs 1,1982).
  **Pressuposto da plataforma (não é regra da CVM):** fica a linha do regime novo (`CLASSE*`). As regras INFO
  `duplicado_na_fonte_valores_iguais` e `duplicado_na_fonte_valores_diferentes` registam os casos com amostra,
  e a bronze guarda as duas linhas. Rever com a CVM antes de usar estes dias em análises sensíveis.
- **Cota zero:** ~2 mil informes por bimestre têm `VL_QUOTA = 0` (regra INFO `cota_positiva`).

## Tabelas

| Camada | Tabela | Chave | Escrita |
|---|---|---|---|
| raw | `ops.raw/cvm/<conjunto>/ingestion_date=…/<run>/` (+ `extraidos/`) | — | ZIP/CSV originais, imutáveis |
| bronze | `cvm_fi_inf_diario`, `cvm_fi_registro_fundo`, `cvm_fi_registro_classe`, `cvm_fi_registro_subclasse`, `cvm_cia_aberta_cad` | — | append, texto, colunas do contrato + `_schema_version`, `_corrupt_record` |
| bronze | `cvm_catalogo_recursos` | — | append por execução |
| silver | `cvm_fi_informe_diario` | (cnpj_classe, id_subclasse, dt_comptc) | SCD1, tipos do dicionário CVM |
| silver | `cvm_fundo`, `cvm_fundo_gestor`, `cvm_fundo_classe`, `cvm_companhia` | ver DDL | SCD2; chaves ausentes do snapshot fecham a versão atual |
| gold | `dim_fundo_classe`, `dim_companhia` | cnpj_classe / cd_cvm | `INSERT OVERWRITE` |
| gold | `fct_fundo_diario` | (cnpj_classe, id_subclasse, data_key) | `INSERT … REPLACE WHERE` desde o 1.º mês alterado |
| gold | `vw_fundos_captacao_mensal`, `vw_fundos_maiores_pl` | — | vistas |

`dim_fundo_classe` junta as classes (RCVM 175) e os fundos ainda sem classe, para cobrir todos os CNPJ do informe
(regra INFO `cobertura_cadastro`).

## Dados pessoais
O cadastro de fundos tem o nome do diretor e o CPF de gestores pessoa física; o de companhias tem nome, e-mail,
telefone e endereço do responsável. Essas colunas (lista em `dados_pessoais` no YAML) ficam só na bronze e no raw
(acesso restrito ao grupo de engenharia) e **não** são selecionadas para silver nem gold.

## Modos de execução

| Modo | Informe diário | Cadastros |
|---|---|---|
| `incremental` | últimos 12 meses, só os que mudaram (ETag) | descarrega se o ETag mudou |
| `backfill` | de `inicio_backfill` (2024-01) até hoje | idem |
| `reprocess` | `data_inicio`..`data_fim` (meses), descarrega sempre | descarrega sempre |

## Qualidade

| Regra | Severidade |
|---|---|
| chave única e preenchida (silver e gold) | CRITICAL |
| CNPJ com 14 dígitos, data e números convertíveis sem perda, número certo de campos (senão quarentena) | HIGH |
| data de competência não futura | HIGH |
| cota > 0, cotistas ≥ 0, cobertura do cadastro, duplicados na fonte (valores iguais / diferentes) | INFO |

## Operação

```bash
python scripts/apply_sql.py --env dev --dir sql/schemas --dir sql/dimensions --dir sql/facts --dir sql/views
python scripts/deploy_workspace.py --env dev --fonte cvm --run backfill
```

```sql
SELECT * FROM findata_dev.gold.vw_fundos_maiores_pl ORDER BY posicao LIMIT 20;
SELECT * FROM findata_dev.gold.vw_fundos_captacao_mensal ORDER BY ano_mes DESC, captacao_liquida DESC;
SELECT entity_name, processing_status, reference_period, source_etag FROM findata_dev.control.source_file_registry
WHERE source_system = 'cvm' ORDER BY received_at DESC;
```
