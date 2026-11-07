"""Logging JSON sanitizado, com correlation_id via contextvar."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime

from forja.observabilidade.sanitizar import sanitizar, sanitizar_texto

correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)
_EXTRAS = ("evento", "tarefa_id", "execucao_id", "metodo", "caminho", "status", "duracao_ms")


class FormatadorJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        dados = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "nivel": record.levelname,
            "logger": record.name,
            "msg": sanitizar_texto(record.getMessage()),
            "correlation_id": correlation_id_var.get(),
        }
        for k in _EXTRAS:
            if hasattr(record, k):
                dados[k] = sanitizar(getattr(record, k))
        if record.exc_info:
            dados["excecao"] = sanitizar_texto(self.formatException(record.exc_info))
        return json.dumps(dados, ensure_ascii=False)


def configurar_logging(nivel: str = "INFO", stream=None) -> None:
    raiz = logging.getLogger("forja")
    raiz.handlers.clear()
    h = logging.StreamHandler(stream or sys.stderr)
    h.setFormatter(FormatadorJson())
    raiz.addHandler(h)
    raiz.setLevel(nivel.upper())
    raiz.propagate = False
