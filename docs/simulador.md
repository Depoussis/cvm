# Simulador de investimento (página "Simulador" do painel)

Responde a: *se eu tivesse comprado R$ X de uma ação, FII ou ETF numa data, quanto teria hoje e de onde viria o
resultado?*

## Como calcula (`app/painel/simulador.py`, testado em `tests/unit/test_painel_streamlit.py`)

1. **Compra:** no primeiro pregão na data escolhida ou depois, ao **preço de fecho da época** (sem ajuste),
   quantidade inteira. A sobra fica em caixa.
2. **Eventos:** no pregão em que um evento entra (`fator_evento` ≠ 1 na `fct_cotacao_diaria`), a quantidade é
   dividida pelo fator de preço:
   - desdobramento 1:2 → ×2;
   - grupamento 10:1 → ÷10;
   - bonificação de 30 % → ×1,3.

   Nas ações, os eventos são os oficiais da B3; em FII e ETF, os detetados na série ([fundamentos.md](fundamentos.md)).
3. **Proventos:** recebe quem tem o papel no fim da data com, valor por ação × quantidade nesse dia. O JCP pode
   descontar 15 % de IR na fonte. Dividendos e rendimentos de FII são isentos para pessoa física.
   - Ações: dividendos e JCP oficiais da B3.
   - FII: rendimento por cota = DY do mês × cota patrimonial (informe mensal da CVM), com data com no último pregão
     do mês.
4. **Reinvestimento (opcional):** compra mais ações no pregão seguinte à data com, ao fecho desse dia, com
   quantidade fracionária.
5. **Resultado:**
   - **valorização** = total de hoje − investido − proventos;
   - **proventos** = soma líquida recebida;
   - **total** = valor das ações + proventos em caixa, também ao ano.
6. **Comparação:** o mesmo valor investido na **Selic** (taxa mensal acumulada, série SGS 4390) e no **BOVA11**
   (preço ajustado).

## Validação dos rendimentos de FII estimados pela CVM

Nos meses em que a B3 publica o valor exato, a estimativa da CVM coincide, com diferença abaixo de 1 %:

| FII | Mês | CVM (DY × cota) | B3 (exato) |
|---|---|---|---|
| KNCR11 | 02/2026 | 1,0002 | 1,00 |
| KNCR11 | 07/2026 | 1,2504 | 1,25 |
| KNCR11 | 08/2026 | 1,1513 | 1,15 |
| HGLG11 | 07/2026 | 1,1688 | 1,17 |
| HGLG11 | 08/2026 | 1,1661 | 1,17 |

As datas com coincidem com as da B3 (KNCR11: 29/05, 30/06, 31/07 e 31/08/2026). A API de fundos da B3 só devolve
cerca de 12 meses, e com registos repetidos, por isso o histórico vem da CVM. FII que informam DY = 0 à CVM (cerca
de 40 %) ficam sem rendimentos no simulador.

## Exemplos (compra de R$ 10 000 em 02/05/2023, JCP com IR, sem reinvestir)

| Papel | Compra | Valorização | Proventos | Total | Selic | Ibovespa (BOVA11) |
|---|---|---|---|---|---|---|
| PETR4 | 439 × R$ 22,74 | +R$ 15 198 (+152 %) | R$ 6 540 | +217,8 % (+39,7 %/ano) | +51,1 % | +104,5 % |
| KNCR11 | 105 × R$ 94,85 | +R$ 1 076 (+10,8 %) | R$ 4 632 | +57,3 % (+14,0 %/ano) | +51,1 % | +104,5 % |
| CMIG4 | — | — | 19 pagamentos | — | — | — |

Na CMIG4, a bonificação de 30 % em 30/04/2024 aparece em "Eventos nas ações", e a quantidade sobe para 1 051,70.

## Limitações

- Preços desde 2021-01 (início do COTAHIST carregado). Papéis com volume médio ≥ R$ 300 mil/dia.
- Não inclui corretagem, emolumentos, IR sobre ganho de capital nem o leilão das frações de bonificações.
- Subscrições (direito de comprar ações novas) não são simuladas.
