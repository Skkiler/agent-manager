"""Redacao de segredos em payloads de evento e logs. Defesa em profundidade, nao garantia unica."""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"
_CHAVES_SENSIVEIS = re.compile(
    r"(token|secret|segredo|senha|password|passwd|api[_-]?key|authorization|cookie|credential|private[_-]?key)",
    re.IGNORECASE,
)
_PADROES_VALOR = [
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(token|secret|password|senha|api[_-]?key)\s*[=:]\s*\S+"),
]
MAX_STR = 2000
MAX_PROFUNDIDADE = 8


def sanitizar_texto(s: str) -> str:
    for p in _PADROES_VALOR:
        s = p.sub(REDACTED, s)
    if len(s) > MAX_STR:
        s = s[:MAX_STR] + "...[truncado]"
    return s


def sanitizar(obj: Any, _nivel: int = 0) -> Any:
    if _nivel > MAX_PROFUNDIDADE:
        return "[profundidade-limitada]"
    if isinstance(obj, dict):
        saida: dict[str, Any] = {}
        for k, v in obj.items():
            ks = str(k)
            saida[ks] = REDACTED if _CHAVES_SENSIVEIS.search(ks) else sanitizar(v, _nivel + 1)
        return saida
    if isinstance(obj, (list, tuple, set)):
        return [sanitizar(x, _nivel + 1) for x in list(obj)[:200]]
    if isinstance(obj, str):
        return sanitizar_texto(obj)
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    return sanitizar_texto(str(obj))
