"""Cliente LSP (Language Server Protocol 3.17) por stdio: JSON-RPC 2.0 com cabecalho Content-Length.

Uma thread le as mensagens do servidor: respostas acordam quem esperava (por id), `publishDiagnostics` fica guardado por
documento, pedidos do servidor (configuracao, registro de capacidades, progresso) recebem resposta padrao para nao travar.
Sem dependencias externas.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote

log = logging.getLogger("forja.lsp")
MAX_MENSAGEM = 32 * 1024 * 1024


class ErroLsp(RuntimeError):
    pass


def chave_uri(uri: str) -> str:
    """Mesma chave para o mesmo arquivo: servidores devolvem o URI com outra codificacao (o Pyright manda 'file:///c%3A/...'
    para 'file:///C:/...'). No Windows o caminho nao diferencia maiusculas."""
    u = unquote(uri or "")
    return u.casefold() if os.name == "nt" else u


class ClienteLsp:
    def __init__(self, comando: list[str], cwd: str, env: dict[str, str] | None = None,
                 configuracao: Callable[[list[dict[str, Any]]], list[Any]] | None = None) -> None:
        self.comando, self.cwd, self.env = comando, cwd, env
        self.configuracao = configuracao  # responde workspace/configuration (itens -> valores)
        self.proc: subprocess.Popen[bytes] | None = None
        self._id = 0
        self._mu = threading.Lock()
        self._escrita = threading.Lock()
        self._esperando: dict[int, tuple[threading.Event, list[Any]]] = {}
        self.diagnosticos: dict[str, list[dict[str, Any]]] = {}
        self._diag_evento: dict[str, threading.Event] = {}
        self.capacidades: dict[str, Any] = {}
        self.vivo = False

    # ------------------------------------------------------------------ processo
    def iniciar(self) -> None:
        criar = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # comando vem da lista fixa de servidores (gerente.SERVIDORES), sem shell e sem texto do usuario
        self.proc = subprocess.Popen(self.comando, cwd=self.cwd, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,  # noqa: S603
                                     stderr=subprocess.DEVNULL, creationflags=criar)
        self.vivo = True
        threading.Thread(target=self._ler, daemon=True, name="forja-lsp-leitura").start()

    def encerrar(self, espera_s: float = 2.0) -> None:
        if self.proc is None:
            return
        try:
            if self.vivo:
                self.pedir("shutdown", None, espera_s)
                self.notificar("exit", None)
        except Exception as e:  # noqa: BLE001 - encerrar e melhor esforco: o processo e morto logo abaixo
            log.debug("shutdown do servidor de linguagem falhou: %s", type(e).__name__)
        self.vivo = False
        try:
            self.proc.wait(timeout=espera_s)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            try:
                self.proc.wait(timeout=espera_s)
            except subprocess.TimeoutExpired:
                log.warning("servidor de linguagem nao terminou depois de kill")
        for fluxo in (self.proc.stdin, self.proc.stdout):
            try:
                if fluxo is not None:
                    fluxo.close()
            except OSError:
                log.debug("fechar o pipe do servidor de linguagem falhou")
        for ev, _ in list(self._esperando.values()):
            ev.set()

    # ------------------------------------------------------------------ envio
    def _enviar(self, msg: dict[str, Any]) -> None:
        if self.proc is None or self.proc.stdin is None or not self.vivo:
            raise ErroLsp("servidor de linguagem parado")
        corpo = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        with self._escrita:
            try:
                self.proc.stdin.write(f"Content-Length: {len(corpo)}\r\n\r\n".encode("ascii") + corpo)
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                self.vivo = False
                raise ErroLsp("o servidor de linguagem fechou a conexao") from e

    def notificar(self, metodo: str, params: Any) -> None:
        self._enviar({"jsonrpc": "2.0", "method": metodo, "params": params})

    def pedir(self, metodo: str, params: Any, tempo_s: float = 5.0) -> Any:
        with self._mu:
            self._id += 1
            id_ = self._id
            ev, caixa = threading.Event(), []
            self._esperando[id_] = (ev, caixa)
        try:
            self._enviar({"jsonrpc": "2.0", "id": id_, "method": metodo, "params": params})
            if not ev.wait(tempo_s):
                try:
                    self.notificar("$/cancelRequest", {"id": id_})
                except ErroLsp:
                    pass
                raise TimeoutError(f"{metodo}: sem resposta em {tempo_s:.0f} s")
        finally:
            self._esperando.pop(id_, None)
        if not caixa:
            raise ErroLsp("o servidor de linguagem parou durante o pedido")
        r = caixa[0]
        if "error" in r:
            raise ErroLsp(f"{metodo}: {str((r['error'] or {}).get('message'))[:200]}")
        return r.get("result")

    # ------------------------------------------------------------------ leitura
    def _ler(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        fluxo = self.proc.stdout
        try:
            while True:
                tamanho = None
                while True:
                    linha = fluxo.readline()
                    if not linha:
                        return
                    linha = linha.strip()
                    if not linha:
                        break
                    if linha.lower().startswith(b"content-length:"):
                        tamanho = int(linha.split(b":", 1)[1])
                if tamanho is None or tamanho > MAX_MENSAGEM:
                    continue
                corpo = fluxo.read(tamanho)
                try:
                    msg = json.loads(corpo.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                self._tratar(msg)
        except (OSError, ValueError) as e:
            log.debug("leitura do servidor de linguagem terminou: %s", type(e).__name__)
        finally:
            self.vivo = False
            for ev, _ in list(self._esperando.values()):
                ev.set()

    def _tratar(self, msg: dict[str, Any]) -> None:
        if "id" in msg and "method" not in msg:  # resposta
            alvo = self._esperando.get(msg["id"])
            if alvo:
                alvo[1].append(msg)
                alvo[0].set()
            return
        metodo, params = msg.get("method"), msg.get("params") or {}
        if metodo == "textDocument/publishDiagnostics":
            uri = chave_uri(params.get("uri", ""))
            self.diagnosticos[uri] = list(params.get("diagnostics") or [])
            ev = self._diag_evento.get(uri)
            if ev:
                ev.set()
            return
        if "id" in msg:  # pedido do servidor: responde para ele nao travar
            resultado: Any = None
            if metodo == "workspace/configuration":
                itens = params.get("items") or []
                resultado = self.configuracao(itens) if self.configuracao else [None] * len(itens)
            elif metodo == "workspace/workspaceFolders":
                resultado = []
            try:
                self._enviar({"jsonrpc": "2.0", "id": msg["id"], "result": resultado})
            except ErroLsp:
                pass

    def tem_diagnosticos(self, uri: str) -> bool:
        return chave_uri(uri) in self.diagnosticos

    def nova_espera(self, uri: str) -> threading.Event:
        """Registre ANTES de mandar a mudanca: a publicacao pode chegar antes de alguem comecar a esperar."""
        ev = threading.Event()
        self._diag_evento[chave_uri(uri)] = ev
        return ev

    def aguardar_diagnosticos(self, uri: str, ev: threading.Event | None, tempo_s: float) -> list[dict[str, Any]]:
        """Espera a proxima publicacao de diagnosticos do documento (ou devolve a ultima, se nao vier a tempo)."""
        uri = chave_uri(uri)
        try:
            if ev is not None:
                ev.wait(max(0.0, tempo_s))
        finally:
            if ev is not None and self._diag_evento.get(uri) is ev:
                self._diag_evento.pop(uri, None)
        return self.diagnosticos.get(uri, [])
