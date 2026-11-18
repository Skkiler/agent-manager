"""Reaproveitamento de processos ACP (Kiro e Codex): o processo fica aberto entre execucoes.

Medido no kiro-cli 3.1.0 (2026-11-18): abrir processo + handshake custa 1,5 a 3,5 s e a 1a sessao ~1,0 s; num processo ja aberto
uma sessao nova (com modo e modelo) levou 0,18 s. Um processo ocioso ocupa ~47 MB.

Regras (seguranca e isolamento):
- uso EXCLUSIVO: um processo atende uma execucao por vez (sai da fila ao ser emprestado);
- ao devolver, as sessoes da execucao sao FECHADAS (session/close: o agente libera MCPs e memoria); sem como fechar e com MCP
  aberto, o processo e encerrado (nao volta para a fila);
- so volta saudavel: erro de transporte, tempo esgotado ou processo morto => encerra;
- teto de usos por processo, tempo maximo ocioso e no maximo N ociosos por comando+ambiente; tudo encerra com o servidor;
- a chave inclui o AMBIENTE do processo: um processo nunca e reaproveitado com outro ambiente (ex.: Kiro x Codex, testes).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from forja.adapters.kiro_acp.cliente import Atualizacao, ClienteAcp, DecisorPermissao

log = logging.getLogger("forja.acp.pool")


def _chave(comando: list[str], env: dict[str, str] | None) -> str:
    bruto = json.dumps([comando, sorted((env or {}).items())], ensure_ascii=True)
    return hashlib.sha256(bruto.encode()).hexdigest()[:16]


class PoolAcp:
    def __init__(self, max_ociosos: int = 2, ocioso_max_s: float = 15 * 60, max_usos: int = 25) -> None:
        self.ativo = True  # preferencia 'reaproveitar_processos'
        self.max_ociosos = max_ociosos
        self.ocioso_max_s = ocioso_max_s
        self.max_usos = max_usos
        self._ociosos: dict[str, list[tuple[float, ClienteAcp]]] = {}
        self._mu = threading.Lock()
        self.estatisticas = {"novos": 0, "reaproveitados": 0, "descartados": 0}

    # ------------------------------------------------------------------ emprestar / devolver
    def obter(self, comando: list[str], env: dict[str, str] | None, cwd: str, decisor: DecisorPermissao,
              on_update: Atualizacao | None, on_notificacao: Callable[[str, dict[str, Any]], None] | None,
              timeout_handshake: float) -> ClienteAcp:
        """Cliente JA iniciado e inicializado (reaproveitado ou novo). Erros de inicio sobem para o chamador (AcpErro)."""
        chave = _chave(comando, env)
        if self.ativo:
            for cliente in self._tirar(chave):
                if cliente.vivo():
                    cliente.reatribuir(decisor, on_update, on_notificacao)
                    cliente.usos += 1
                    cliente.reaproveitado = True
                    cliente.chave_pool = chave  # type: ignore[attr-defined]
                    self.estatisticas["reaproveitados"] += 1
                    return cliente
                self._descartar(cliente)
        cliente = ClienteAcp(comando, cwd=cwd, decisor_permissao=decisor, on_update=on_update, on_notificacao=on_notificacao,
                             env_base=env)
        cliente.chave_pool = chave  # type: ignore[attr-defined]
        try:
            cliente.iniciar()
            cliente.inicializar(timeout_handshake)
        except Exception:
            cliente.encerrar()
            raise
        cliente.usos = 1
        cliente.filtrar_sessoes = True
        self.estatisticas["novos"] += 1
        return cliente

    def devolver(self, cliente: ClienteAcp, saudavel: bool) -> None:
        """Volta para a fila so se tudo estiver em ordem; senao encerra o processo (falha segura)."""
        chave = getattr(cliente, "chave_pool", None)
        if not (self.ativo and saudavel and chave and cliente.vivo() and cliente.usos < self.max_usos):
            self._descartar(cliente)
            return
        try:
            fechou = cliente.fechar_sessoes()
        except Exception:  # noqa: BLE001
            fechou = False
        if not fechou or not cliente.vivo():
            self._descartar(cliente)
            return
        excedente: list[ClienteAcp] = []
        with self._mu:
            fila = self._ociosos.setdefault(chave, [])
            fila.append((time.monotonic(), cliente))
            while len(fila) > self.max_ociosos:
                excedente.append(fila.pop(0)[1])
        for c in excedente:
            self._descartar(c)

    def _tirar(self, chave: str) -> list[ClienteAcp]:
        """Remove da fila (LIFO: o mais recente primeiro) e ja descarta os vencidos."""
        agora = time.monotonic()
        vencidos: list[ClienteAcp] = []
        with self._mu:
            fila = self._ociosos.get(chave, [])
            validos = [(t, c) for t, c in fila if agora - t <= self.ocioso_max_s]
            vencidos = [c for t, c in fila if agora - t > self.ocioso_max_s]
            escolhido = validos.pop() if validos else None
            self._ociosos[chave] = validos
        for c in vencidos:
            self._descartar(c)
        return [escolhido[1]] if escolhido else []

    def _descartar(self, cliente: ClienteAcp) -> None:
        self.estatisticas["descartados"] += 1
        try:
            cliente.encerrar()
        except Exception:  # noqa: BLE001
            log.debug("falha ao encerrar processo ACP descartado")

    # ------------------------------------------------------------------ ciclo de vida
    def aquecer(self, comando: list[str], env: dict[str, str] | None, cwd: str, timeout_handshake: float = 30.0) -> None:
        """Abre UM processo antes da primeira tarefa (handshake sem custo de creditos). Melhor esforco, em segundo plano."""
        def _rodar() -> None:
            try:
                c = self.obter(comando, env, cwd, lambda _p: None, None, None, timeout_handshake)
                self.devolver(c, True)
            except Exception as e:  # noqa: BLE001 - sem aquecimento, a 1a tarefa so demora um pouco mais
                log.info("aquecimento do processo ACP falhou: %s", type(e).__name__)
        threading.Thread(target=_rodar, name="acp-aquecer", daemon=True).start()

    def ociosos(self) -> int:
        with self._mu:
            return sum(len(f) for f in self._ociosos.values())

    def encerrar_todos(self) -> None:
        with self._mu:
            todos = [c for f in self._ociosos.values() for _, c in f]
            self._ociosos.clear()
        for c in todos:
            self._descartar(c)
