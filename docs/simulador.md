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

## IR na venda (quadro "Resumo da simulação")

O simulador mostra o que ficaria **se vendesse tudo hoje e pagasse o IR** (pessoa física, operações comuns, regras
de 2026, `imposto_venda` em `app/painel/simulador.py`):

| Classe | Alíquota sobre o lucro | Isenção |
|---|---|---|
| Ações | 15 % | vendas de ações até R$ 20 mil no mês (opção ligada por omissão; supõe que é a única venda do mês) |
| FII | 20 % | nenhuma |
| ETF | 15 % | nenhuma |

- Lucro = valor de venda − custo de aquisição (compra inicial + compras com proventos reinvestidos).
- As ações recebidas em bonificação entram com custo zero. Na realidade a empresa informa um custo por ação, o que
  reduz um pouco o imposto.
- Prejuízo não paga imposto (e poderia compensar lucros futuros, o que não é simulado).
- Dividendos e rendimentos de FII são isentos; o JCP já vem com 15 % retidos (opção).
- Para comparar, a **Selic líquida** aplica a tabela regressiva da renda fixa: 22,5 % até 180 dias, 20 % até 360,
  17,5 % até 720 e 15 % acima disso.

## Exemplos (compra de R$ 10 000 em 02/05/2023, JCP com IR, sem reinvestir, venda em 15/10/2026)

| | PETR4 | KNCR11 (FII) |
|---|---|---|
| Compra | 439 × R$ 22,74 = R$ 9 982,86 (sobra R$ 17,14) | 105 × R$ 94,85 = R$ 9 959,25 |
| Valor das ações hoje | 439 × R$ 57,36 = R$ 25 181,04 | 105 × R$ 105,10 = R$ 11 035,50 |
| Proventos recebidos (líquidos) | R$ 6 539,54 (IR do JCP retido: R$ 421,75) | R$ 4 632,42 |
| **Total bruto** | **R$ 31 720,58** (+217,8 %) | **R$ 15 667,92** (+57,3 %) |
| IR sobre o lucro da venda | −R$ 2 279,73 (15 % de R$ 15 198,18) | −R$ 215,25 (20 % de R$ 1 076,25) |
| **Total líquido** | **R$ 29 440,85** | **R$ 15 452,67** |
| Lucro líquido | R$ 19 457,99 (+194,9 %; +36,8 % ao ano) | R$ 5 493,42 (+55,2 %; +13,6 % ao ano) |
| Selic no período | +51,1 % bruto, +43,4 % líquido | igual |
| Ibovespa (BOVA11) | +104,5 % antes de IR | igual |

Na CMIG4, a bonificação de 30 % em 30/04/2024 aparece em "Eventos nas ações", e a quantidade sobe para 1 051,70.

## Limitações

- Preços desde 2021-01 (início do COTAHIST carregado). Papéis com volume médio ≥ R$ 300 mil/dia.
- Não inclui corretagem, emolumentos, IR sobre ganho de capital nem o leilão das frações de bonificações.
- Subscrições (direito de comprar ações novas) não são simuladas.
