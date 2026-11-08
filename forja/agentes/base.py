"""Contrato de provedor de agente. Kiro (ACP) e o mock implementam a mesma interface."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from forja.dominio.contratos import ResultadoAgente


class ControleExecucao:
    """Canal cooperativo entre orquestrador e provedor: cancelar, pausar, checkpoint, eventos."""

    def __init__(
        self,
        persistir_checkpoint: Callable[[dict[str, Any]], None],
        emitir: Callable[[str, dict[str, Any]], None],
        aprovar: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None,
    ) -> None:
        self.cancelar_ev = threading.Event()
        self.pausar_ev = threading.Event()
        self._persistir = persistir_checkpoint
        self._emitir = emitir
        self._aprovar = aprovar

    def solicitar_aprovacao(self, itens: list[dict[str, Any]]) -> dict[str, Any]:
        """Pede ao operador UMA decisao para um grupo de acoes. Sem canal de aprovacao: nega tudo.

        Retorna {"aprovados": [ids], "adendo": str, "lembrar": bool}.
        """
        if self._aprovar is None:
            return {"aprovados": [], "adendo": "", "lembrar": False}
        return self._aprovar(itens)

    def cancelado(self) -> bool:
        return self.cancelar_ev.is_set()

    def pausado(self) -> bool:
        return self.pausar_ev.is_set()

    def registrar_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        self._persistir(checkpoint)

    def evento(self, tipo: str, payload: dict[str, Any] | None = None) -> None:
        self._emitir(tipo, payload or {})

    def dormir(self, segundos: float) -> None:
        """Espera interrompivel por cancelamento/pausa."""
        fim = time.monotonic() + segundos
        while time.monotonic() < fim and not (self.cancelado() or self.pausado()):
            time.sleep(min(0.02, max(0.0, fim - time.monotonic())))


class ProvedorAgente(Protocol):
    id: str
    mock: bool

    def executar(
        self, tarefa: dict[str, Any], checkpoint: dict[str, Any], ctl: ControleExecucao
    ) -> ResultadoAgente: ...
