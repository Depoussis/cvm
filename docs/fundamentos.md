# Fundamentos (DFP/ITR) e proventos (dividendos, JCP, eventos societários)

Duas fontes novas que alimentam os indicadores da página Bolsa (P/L, P/VP, ROE, DY) e o modelo preditivo
([modelo_preditivo.md](modelo_preditivo.md)).

## Demonstrações financeiras da CVM (DFP e ITR)

| Conjunto | Pacote CKAN | Ficheiro | Notas |
|---|---|---|---|
| DFP (anual) | `cia_aberta-doc-dfp` | `CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_AAAA.zip` | ~13 MB, 19 CSV |
| ITR (1.º a 3.º trimestre) | `cia_aberta-doc-itr` | `CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_AAAA.zip` | ~31 MB |

De cada ZIP carregam-se oito CSV (contrato em `config/datasets/cvm.yaml`):
- o índice dos documentos, com a **data de entrega** à CVM;
- DRE, BPA e BPP, consolidados e individuais;
- a composição do capital.

Os cabeçalhos foram verificados de 2019 a 2026 e são iguais em todos os anos. A composição do capital só existe a
partir de 2021, por isso o backfill começa em 2021. DFP e ITR partilham as tabelas bronze (`cvm_demo_*`), e
`_source_entity` distingue a origem.

**Silver** (`notebooks/silver/cvm.py`, entidade `cvm_demonstracoes`):

| Tabela | Conteúdo |
|---|---|
| `cvm_demo_documento` | uma linha por documento e versão, com `dt_receb` |
| `cvm_demo_conta` | contas da DRE e dos balanços, só o exercício corrente (`ORDEM_EXERC = ÚLTIMO`), até ao 3.º nível, versão mais alta, em reais (a CVM publica em milhares) |
| `cvm_demo_capital` | ações integralizadas e em tesouraria |

Um documento com linhas novas é recalculado a partir de toda a bronze desse documento. Assim, uma versão antiga
recarregada mais tarde nunca se sobrepõe a uma mais recente.

**Gold** `fct_fundamentos_trimestre` (`src/gold/fundamentos.py`), uma linha por companhia e trimestre:
- **Trimestre:** a ITR traz o trimestre isolado (3 meses). O 4.º trimestre = anual da DFP − os três trimestres.
  Se a empresa também entregou uma ITR do 4.º trimestre (8 casos), fica a DFP.
- **12 meses:** soma dos últimos 4 trimestres consecutivos.
- **Contas pela descrição:** os códigos mudam com o tipo de empresa. Por exemplo, o lucro consolidado é 3.11 na
  indústria, 3.09 nos bancos e 3.13 nas seguradoras; o PL é 2.03 ou 2.08. As regras estão na docstring do módulo
  e nos testes. O lucro é o atribuído aos controladores, e o PL exclui os não controladores.
- **`data_publicacao`:** a primeira entrega do documento. É esta data, e não o fim do trimestre, que o modelo usa.

Resultado em 16/10/2026: 15 536 trimestres de 878 companhias, de 2021-03 a 2026-06. Conferências:

| Companhia | Lucro 12 meses | PL |
|---|---|---|
| Petrobras (2025) | R$ 110,1 bi | R$ 415,8 bi |
| WEG (2025) | R$ 6,4 bi | R$ 17,4 bi |
| Itaú (2025) | R$ 44,9 bi | — |

**Número de ações:** algumas empresas declaram a composição do capital à CVM **em milhares** (o Itaú envia 10,8
milhões em vez de 11 mil milhões). Por isso o valor de mercado usa o número de ações da B3 (abaixo), e não o da CVM.

## Proventos e eventos societários (B3)

Fonte: a API pública das páginas "Empresas listadas" de b3.com.br (`src/ingestion/b3/proventos.py`). Não é um
produto de dados documentado, por isso as chaves esperadas de cada resposta fazem parte do contrato: se faltar
alguma, a carga falha. Há três chamadas, com parâmetros em JSON base64 no URL:
- `GetInitialCompanies`: lista das 3 543 empresas (paginada);
- `GetListedSupplementCompany`: número de ações ON/PN e eventos em ações (desdobramentos, grupamentos,
  bonificações), por emissor;
- `GetListedCashDividends`: histórico completo de dividendos, JCP e rendimentos por ação, com a data com
  (paginado; a PETROBRAS tem 343 registos desde 2007).

Job semanal **`findata_dev_b3_proventos`** (domingo 05:00, pelo ADF `pl_findata_semanal`):
`bronze_b3_proventos → silver_b3_proventos → gold_b3_proventos`. Cobre as companhias com ações negociadas nos
últimos 2 anos.

Primeira carga (16/10/2026):
- 310 empresas, 725 pedidos, 0 falhas;
- 18 536 proventos desde 1995 (9 170 JCP, 8 925 dividendos, 365 rendimentos, 76 restituições de capital);
- 716 eventos em ações (171 desdobramentos, 232 grupamentos, 231 bonificações).

| Camada | Tabela | Conteúdo |
|---|---|---|
| Bronze | `b3_empresas`, `b3_empresa_complemento`, `b3_proventos_dinheiro`, `b3_eventos_acoes` | cópia completa por execução, texto; todas as respostas num JSON Lines no volume raw |
| Silver | `b3_provento` | SCD1, chave emissor + espécie + tipo + data com + valor |
| Silver | `b3_evento_acao` | SCD1, oficial |
| Silver | `b3_empresa` | CNPJ e número de ações |
| Gold | `fct_provento` | por ticker (a raiz do emissor + a espécie, ex.: PETR + PN → PETR4): data ex = primeiro pregão depois da data com; `yield_evento` = valor / fecho na data com; `valor_ajustado` = valor × fatores de eventos posteriores (comparável com o preço ajustado) |
| Gold | `vw_b3_dividendos_anuais`, `vw_b3_dy_12m` | soma por ano e DY de 12 meses |

Exemplos de DY por ano:

| Ação | DY |
|---|---|
| PETR4 | 49,9 % (2022), 24,7 % (2023), 16,6 % (2024) |
| TAEE11 | 8–10 % ao ano |
| ITUB4 | 7,6 % nos últimos 12 meses |

### Eventos oficiais substituem a heurística nas ações

Ao comparar os eventos oficiais com a heurística da gold de cotações (regra INFO `evento_oficial_nao_detetado`),
**38 dos 105 desdobramentos/grupamentos desde 2021 não tinham sido detetados**, e nenhuma bonificação o era. As
bonificações (ações dadas aos acionistas) são frequentes e afetam ações muito líquidas. Por exemplo, em CMIG4 30 %
(2024), EGIE3 40 % (2025), ITUB4 3 % (2025) e BBDC4 10 % (2022), o preço cai na data ex sem que os acionistas
percam dinheiro. A heurística também falhou o desdobramento 1:4 da VAMO3 (queda de 77 %, fora da tolerância de 8 %).

Desde esta versão, `src/gold/cotacoes.py` usa o fator oficial nas ações dos emissores cobertos pela B3:

| Evento | Fator do preço |
|---|---|
| Desdobramento f % | 1/(1+f/100) |
| Bonificação f % | 1/(1+f/100) |
| Grupamento f (fração) | 1/f |

Os eventos da mesma data multiplicam-se: o desdobramento de 9 900 % mais o grupamento de 0,01 da TIMS3 dão 1. A
heurística ficou só para FII e ETF. A gold foi reconstruída (`run_mode=reprocess`). Eventos novos chegam pela carga
semanal e recalculam o ticker por Change Data Feed ([streaming.md](streaming.md)).
