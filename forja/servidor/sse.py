"""Fluxo SSE com replay por Last-Event-ID. O cursor e o 'seq' monotono do banco."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from typing import Any

from forja.orquestracao.servico import Servico

MAX_REPLAY = 1000
RECENTES_PADRAO = 50


def formatar(e: dict[str, Any]) -> str:
    dados = {k: e[k] for k in ("seq", "event_id", "tipo", "ts", "projeto_id", "tarefa_id", "execucao_id",
                               "correlation_id", "payload")}
    return f"id: {e['seq']}\nevent: {e['tipo']}\ndata: {json.dumps(dados, ensure_ascii=False)}\n\n"


def gerar(
    servico: Servico,
    after: int | None,
    projeto_id: str | None = None,
    follow: bool = True,
    parar: Callable[[], bool] = lambda: False,
    intervalo: float = 0.4,
    heartbeat: float = 15.0,
) -> Iterator[str]:
    ultimo = servico.ultimo_seq()
    if after is None:
        cursor = max(0, ultimo - RECENTES_PADRAO)
    else:
        cursor = max(0, after)
        if ultimo - cursor > MAX_REPLAY:
            cursor = ultimo - MAX_REPLAY
            yield f"event: replay.truncado\ndata: {json.dumps({'a_partir_de': cursor})}\n\n"
    ultimo_envio = time.monotonic()
    while True:
        eventos = servico.eventos_apos(cursor, 200, projeto_id)
        for e in eventos:
            cursor = e["seq"]
            ultimo_envio = time.monotonic()
            yield formatar(e)
        if eventos:
            continue
        if not follow or parar():
            return
        if time.monotonic() - ultimo_envio >= heartbeat:
            ultimo_envio = time.monotonic()
            yield ": heartbeat\n\n"
        time.sleep(intervalo)
