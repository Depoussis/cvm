"""Pedidos HTTP às fontes públicas, com retries, backoff exponencial e pausa entre pedidos."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

log = logging.getLogger(__name__)

REPETIVEIS = {408, 425, 429, 500, 502, 503, 504}


@dataclass
class Resposta:
    url: str
    status: int
    conteudo: bytes
    etag: str | None
    last_modified: str | None


class ErroFonte(RuntimeError):
    """A fonte devolveu um erro definitivo (ex.: 400, 404) ou esgotou as tentativas."""


class ClienteHttp:
    def __init__(self, cfg_http: dict[str, Any], sessao: requests.Session | None = None, dormir=time.sleep):
        self.timeout = cfg_http["timeout_s"]
        self.tentativas = cfg_http["tentativas"]
        self.backoff = cfg_http["backoff_base_s"]
        self.pausa = cfg_http["pausa_entre_pedidos_s"]
        self.sessao = sessao or requests.Session()
        self.sessao.headers["User-Agent"] = cfg_http["user_agent"]
        self.sessao.headers["Accept"] = "application/json"
        self._dormir = dormir
        self._ultimo = 0.0

    def get(self, url: str, params: dict[str, str] | None = None, aceitar: frozenset[int] = frozenset()) -> Resposta:
        """GET com retries. `aceitar`: estados não-200 devolvidos ao chamador (ex.: 404 = sem dados no SGS)."""
        for tentativa in range(1, self.tentativas + 1):
            espera = self.pausa - (time.monotonic() - self._ultimo)
            if espera > 0:
                self._dormir(espera)
            self._ultimo = time.monotonic()
            try:
                r = self.sessao.get(url, params=params, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as e:
                motivo = f"{type(e).__name__}: {e}"
            else:
                if r.status_code == 200 or r.status_code in aceitar:
                    return Resposta(r.url, r.status_code, r.content, r.headers.get("ETag"), r.headers.get("Last-Modified"))
                if r.status_code not in REPETIVEIS:
                    raise ErroFonte(f"HTTP {r.status_code} em {r.url}: {r.text[:300]}")
                motivo = f"HTTP {r.status_code}"
            if tentativa == self.tentativas:
                raise ErroFonte(f"{motivo} após {tentativa} tentativas: {url}")
            atraso = self.backoff * 2 ** (tentativa - 1)
            log.warning("pedido falhou (%s), nova tentativa %d/%d em %ss", motivo, tentativa + 1, self.tentativas, atraso)
            self._dormir(atraso)
        raise AssertionError("inalcançável")
