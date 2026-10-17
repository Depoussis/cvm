"""Proventos e eventos societários das companhias listadas na B3 (API pública do site da B3, "Empresas listadas").

Funções puras (sem Spark nem rede), testadas localmente. A API não é um produto de dados documentado: é a que
alimenta as páginas de cada empresa em b3.com.br. Os parâmetros vão em JSON codificado em base64 no próprio URL.
Confirmado em 16/10/2026:
- GetInitialCompanies: lista paginada das empresas (código de emissor de 4 letras, CNPJ, nome de pregão);
- GetListedSupplementCompany: número de ações ON/PN e eventos em ações (desdobramentos, grupamentos, bonificações);
- GetListedCashDividends: histórico completo de dividendos e JCP por ação, paginado (ex.: PETROBRAS desde 2007).
"""
from __future__ import annotations

import base64
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

BASE = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall"

# Contrato: chaves esperadas em cada tipo de registo. Chaves em falta → schema drift (a execução falha).
CHAVES_EMPRESA = {"issuingCompany", "companyName", "tradingName", "cnpj", "codeCVM", "segment"}
CHAVES_COMPLEMENTO = {"tradingName", "code", "codeCVM", "numberCommonShares", "numberPreferredShares",
                      "totalNumberShares", "stockDividends", "cashDividends"}
CHAVES_DINHEIRO = {"typeStock", "dateApproval", "valueCash", "ratio", "corporateAction", "lastDatePriorEx",
                   "closingPricePriorExDate", "quotedPerShares"}
CHAVES_EVENTO = {"isinCode", "factor", "approvedOn", "label", "lastDatePrior"}


# Fundos listados (FII): GetListedSupplementFunds devolve os rendimentos exatos por cota, mas só dos últimos ~12
# meses (confirmado em 17/10/2026). A silver nunca apaga, por isso o histórico exato cresce a cada carga semanal.
BASE_FUNDOS = "https://sistemaswebb3-listados.b3.com.br/fundsProxy/fundsCall"
TIPO_FUNDO_FII = 7
CHAVES_FII = {"isinCode", "rate", "label", "lastDatePrior", "paymentDate"}


def url_fundo(identificador: str, tipo_fundo: int = TIPO_FUNDO_FII) -> str:
    """Página de um fundo listado pela raiz de 4 letras do ticker (ex.: 'KNCR' para KNCR11)."""
    return f"{BASE_FUNDOS}/GetListedSupplementFunds/" + _b64(
        {"cnpj": "0", "identifierFund": identificador, "typeFund": tipo_fundo})


def _b64(parametros: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(parametros, separators=(",", ":")).encode()).decode()


def url_empresas(pagina: int, tamanho: int = 120) -> str:
    return f"{BASE}/GetInitialCompanies/" + _b64({"language": "pt-br", "pageNumber": pagina, "pageSize": tamanho})


def url_complemento(emissor: str) -> str:
    return f"{BASE}/GetListedSupplementCompany/" + _b64({"issuingCompany": emissor, "language": "pt-br"})


def url_dinheiro(nome_pregao: str, pagina: int, tamanho: int = 120) -> str:
    # a API não encontra nomes com barra ("AMBEV S/A" devolve 0 registos, "AMBEV SA" devolve o histórico), como o
    # site da B3, que a retira antes de pedir
    return f"{BASE}/GetListedCashDividends/" + _b64(
        {"language": "pt-br", "pageNumber": pagina, "pageSize": tamanho, "tradingName": nome_pregao.replace("/", "")})


def numero(texto: str | None) -> Decimal | None:
    """'0,67407131' → Decimal('0.67407131'); '1.234,5' → 1234.5; vazio → None."""
    if texto is None or not str(texto).strip():
        return None
    try:
        return Decimal(str(texto).strip().replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def data_br(texto: str | None) -> date | None:
    """'21/08/2026' → date(2026, 8, 21); vazio ou inválido → None."""
    if not texto or not str(texto).strip():
        return None
    try:
        return datetime.strptime(str(texto).strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def chaves_em_falta(registo: dict[str, Any], esperadas: set[str]) -> set[str]:
    return esperadas - set(registo)


def paginas(resposta: dict[str, Any]) -> int:
    """Número total de páginas indicado pela API (0 quando não há registos)."""
    return int((resposta.get("page") or {}).get("totalPages") or 0)


# Campos da API → colunas da bronze (texto, como recebido). Campos novos da API são ignorados; os de CHAVES_* são
# obrigatórios.
CAMPOS = {
    "empresas": {"issuingCompany": "emissor", "companyName": "razao_social", "tradingName": "nome_pregao",
                 "cnpj": "cnpj", "codeCVM": "codigo_cvm", "segment": "segmento", "marketIndicator": "indicador_mercado",
                 "type": "tipo", "status": "situacao", "dateListing": "data_listagem"},
    "complemento": {"tradingName": "nome_pregao", "code": "codigo", "codeCVM": "codigo_cvm",
                    "numberCommonShares": "qtd_acoes_on", "numberPreferredShares": "qtd_acoes_pn",
                    "totalNumberShares": "qtd_acoes_total", "segment": "segmento", "stockCapital": "capital_social",
                    "quotedPerSharSince": "cotacao_por_acao_desde"},
    "eventos": {"assetIssued": "ativo_emitido", "isinCode": "isin", "factor": "fator", "approvedOn": "data_aprovacao",
                "label": "tipo_evento", "lastDatePrior": "data_com", "remarks": "observacoes"},
    "dinheiro": {"typeStock": "tipo_acao", "dateApproval": "data_aprovacao", "valueCash": "valor",
                 "ratio": "proporcao", "corporateAction": "tipo_provento", "lastDatePriorEx": "data_com",
                 "dateClosingPricePriorExDate": "data_fecho_data_com", "closingPricePriorExDate": "fecho_data_com",
                 "quotedPerShares": "cotacao_por_acoes", "corporateActionPrice": "provento_pct_preco",
                 "lastDateTimePriorEx": "data_hora_com"},
    "fii": {"assetIssued": "ativo_emitido", "isinCode": "isin", "rate": "valor", "label": "tipo_provento",
            "lastDatePrior": "data_com", "paymentDate": "data_pagamento", "approvedOn": "data_aprovacao",
            "relatedTo": "referencia", "remarks": "observacoes"},
}


def registo(tipo: str, origem: dict[str, Any], **extra: str) -> dict[str, str | None]:
    """Converte um registo da API nas colunas da bronze (tudo texto) mais as colunas extra (ex.: emissor)."""
    linha = {col: (None if origem.get(chave) is None else str(origem.get(chave)))
             for chave, col in CAMPOS[tipo].items()}
    return {**extra, **linha}
