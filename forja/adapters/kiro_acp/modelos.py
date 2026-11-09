"""Lista os modelos que a conta Kiro aceita (`kiro-cli chat --list-models`), com o custo relativo em creditos.

Somente leitura e sem consumir creditos. Comando fixo, sem shell e sem entrada do usuario. O resultado e cacheado
por alguns minutos para nao abrir um processo a cada abertura da tela de configuracao.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from collections.abc import Callable

_LINHA = re.compile(r"^(?P<padrao>\*)?\s*(?P<id>[A-Za-z0-9][A-Za-z0-9._:/-]{0,79})\s+(?P<custo>\d+(?:\.\d+)?)x credits\s*(?P<desc>.*)$")
TTL_S = 600
TIMEOUT_S = 20


def parse_modelos(saida: str) -> list[dict]:
    """Interpreta a saida do CLI; linhas que nao casam sao ignoradas (formato pode mudar entre versoes)."""
    modelos = []
    for linha in saida.splitlines():
        m = _LINHA.match(linha.strip())
        if m:
            modelos.append({"id": m["id"], "custo": float(m["custo"]), "descricao": m["desc"].strip()[:160],
                            "padrao": bool(m["padrao"])})
    return modelos


def _executar(cli: str) -> str:
    p = subprocess.run([cli, "chat", "--list-models"], capture_output=True, text=True, encoding="utf-8",  # noqa: S603
                       errors="replace", timeout=TIMEOUT_S, check=False, stdin=subprocess.DEVNULL)
    return p.stdout


class CatalogoModelos:
    def __init__(self, cli: str | None, executar: Callable[[str], str] = _executar, agora: Callable[[], float] = time.monotonic) -> None:
        self.cli, self._executar, self._agora = cli, executar, agora
        self._cache: tuple[float, list[dict]] | None = None
        self._mu = threading.Lock()

    def listar(self) -> dict:
        if not self.cli:
            return {"modelos": [], "aviso": "Kiro CLI nao encontrado: informe o modelo manualmente."}
        with self._mu:
            if self._cache and self._agora() - self._cache[0] < TTL_S:
                return {"modelos": self._cache[1], "aviso": None}
            try:
                modelos = parse_modelos(self._executar(self.cli))
            except (OSError, subprocess.SubprocessError):
                return {"modelos": [], "aviso": "Nao foi possivel consultar os modelos agora; informe manualmente."}
            if not modelos:
                return {"modelos": [], "aviso": "O CLI nao devolveu modelos (login necessario?); informe manualmente."}
            self._cache = (self._agora(), modelos)
            return {"modelos": modelos, "aviso": None}
