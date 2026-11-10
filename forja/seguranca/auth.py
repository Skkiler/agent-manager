"""Autenticacao por token local (loopback/tunel SSH) e limitador de taxa. Nenhum segredo e logado."""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from pathlib import Path

from forja.config import Configuracoes

ARQUIVO_TOKEN = "api_token.txt"  # noqa: S105 - nome de arquivo, nao um segredo
MIN_TOKEN = 24


def carregar_token(cfg: Configuracoes) -> str | None:
    """Token da API. Prioridade: variavel APP_API_TOKEN; senao arquivo na pasta de credenciais do usuario (fora do Git)."""
    if not cfg.app_require_auth:
        return None
    if cfg.app_api_token is not None:
        valor = cfg.app_api_token.get_secret_value()
        if len(valor) < MIN_TOKEN:
            raise ValueError(f"APP_API_TOKEN deve ter pelo menos {MIN_TOKEN} caracteres.")
        return valor
    caminho = Path(cfg.credenciais_dir) / ARQUIVO_TOKEN
    if caminho.exists():
        valor = caminho.read_text(encoding="utf-8").strip()
        if len(valor) >= MIN_TOKEN:
            return valor
    caminho.parent.mkdir(parents=True, exist_ok=True)
    valor = secrets.token_urlsafe(32)
    caminho.write_text(valor + "\n", encoding="utf-8")
    return valor


def token_confere(enviado: str | None, esperado: str) -> bool:
    return enviado is not None and hmac.compare_digest(enviado.encode(), esperado.encode())


def extrair_bearer(cabecalho: str | None) -> str | None:
    if not cabecalho:
        return None
    partes = cabecalho.split(" ", 1)
    if len(partes) != 2 or partes[0].lower() != "bearer":
        return None
    return partes[1].strip() or None


class LimitadorTaxa:
    """Janela fixa de 60 s por cliente. Em memoria; suficiente para uso local/LAN restrita."""

    def __init__(self, limite_por_minuto: int) -> None:
        self.limite = limite_por_minuto
        self._contagem: dict[str, tuple[int, int]] = {}
        self._mu = threading.Lock()

    def permitir(self, cliente: str) -> bool:
        janela = int(time.time() // 60)
        with self._mu:
            j, n = self._contagem.get(cliente, (janela, 0))
            if j != janela:
                j, n = janela, 0
            n += 1
            self._contagem[cliente] = (j, n)
            if len(self._contagem) > 10_000:
                self._contagem = {k: v for k, v in self._contagem.items() if v[0] == janela}
            return n <= self.limite
