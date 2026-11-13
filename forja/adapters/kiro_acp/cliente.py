"""Cliente ACP (Agent Client Protocol) sobre stdio: JSON-RPC 2.0 delimitado por linhas.

- stdout do processo = protocolo; stderr e lido a parte (nunca misturado) e sanitizado.
- Sem shell: o comando e uma lista de argumentos.
- Capacidades de cliente anunciadas sao MINIMAS (sem fs/terminal): pedidos fs/* e terminal/* retornam
  'method not found'. Permissoes de ferramenta sao negadas por padrao.
- Nenhuma credencial e lida, armazenada ou registrada aqui; a autenticacao pertence ao proprio kiro-cli.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import subprocess
import threading
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FuturoTimeout
from typing import Any

from forja.observabilidade.sanitizar import sanitizar_texto

log = logging.getLogger("forja.acp")
PROTOCOLO = 1
MAX_LINHA = 4 * 1024 * 1024


class AcpErro(Exception):
    def __init__(self, mensagem: str, codigo: int | None = None) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo


class AcpCliAusente(AcpErro):
    pass


class AcpAutenticacaoNecessaria(AcpErro):
    pass


class AcpDesconectado(AcpErro):
    pass


class AcpTimeout(AcpErro):
    pass


class AcpProtocoloNaoSuportado(AcpErro):
    pass


class AcpMetodoNaoSuportado(AcpErro):
    pass


Atualizacao = Callable[[str, dict[str, Any]], None]  # (session_id, update)
DecisorPermissao = Callable[[dict[str, Any]], str | None]  # request -> optionId | None (cancelar)


def decisor_negar_tudo(pedido: dict[str, Any]) -> str | None:
    """Politica padrao: escolhe uma opcao de rejeicao; sem opcao de rejeicao, cancela o pedido."""
    for op in pedido.get("options", []):
        if str(op.get("kind", "")).startswith("reject"):
            return str(op.get("optionId"))
    return None


def _traduz_erro(err: dict[str, Any]) -> AcpErro:
    codigo = err.get("code")
    msg = sanitizar_texto(str(err.get("message", "erro desconhecido")))
    baixa = msg.lower()
    if "authentication required" in baixa or "not logged in" in baixa:
        return AcpAutenticacaoNecessaria(msg, codigo)
    if codigo == -32601:
        return AcpMetodoNaoSuportado(msg, codigo)
    return AcpErro(msg, codigo)


class ClienteAcp:
    def __init__(
        self,
        comando: list[str],
        cwd: str | None = None,
        decisor_permissao: DecisorPermissao = decisor_negar_tudo,
        on_update: Atualizacao | None = None,
        env_extra: dict[str, str] | None = None,
        on_notificacao: Callable[[str, dict[str, Any]], None] | None = None,
        env_base: dict[str, str] | None = None,
    ) -> None:
        self._env_base = env_base  # None = ambiente do processo; agentes de terceiros recebem um ambiente LIMPO (sem segredos)
        self._on_notificacao = on_notificacao  # extensoes do agente (ex.: _kiro/mcp/status), fora de session/update
        self.comando = comando
        self.cwd = cwd
        self._decisor = decisor_permissao
        self._on_update = on_update
        self._env_extra = env_extra or {}
        self._proc: subprocess.Popen[str] | None = None
        self._ids = itertools.count(1)
        self._pend: dict[int, Future] = {}
        self._mu = threading.Lock()
        self._escrita = threading.Lock()
        self._stderr: deque[str] = deque(maxlen=50)
        self.agent_info: dict[str, Any] = {}
        self.capacidades: dict[str, Any] = {}
        self.opcoes_sessao: list[dict[str, Any]] = []  # configOptions da sessao (modelo, esforco, modo...)
        self.auth_methods: list[dict[str, Any]] = []
        self._leitores: list[threading.Thread] = []
        self.permissoes_negadas = 0
        self.permissoes_aprovadas = 0
        self._tool_calls: dict[str, dict[str, Any]] = {}
        self.permissoes_vistas: list[dict[str, Any]] = []
        self._fechado = False

    # ---------------------------------------------------------------- ciclo de vida
    def iniciar(self) -> None:
        env = {**(os.environ if self._env_base is None else self._env_base), **self._env_extra}
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._proc = subprocess.Popen(  # noqa: S603 - lista de args, sem shell
                self.comando, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1, cwd=self.cwd, env=env,
                creationflags=flags,
            )
        except FileNotFoundError as e:
            raise AcpCliAusente("Executavel do Kiro CLI nao encontrado.") from e
        except OSError as e:
            raise AcpErro(f"Falha ao iniciar o processo ACP: {sanitizar_texto(str(e))}") from e
        self._leitores = [
            threading.Thread(target=self._ler_stdout, name="acp-stdout", daemon=True),
            threading.Thread(target=self._ler_stderr, name="acp-stderr", daemon=True),
        ]
        for th in self._leitores:
            th.start()

    def encerrar(self) -> None:
        self._fechado = True
        p = self._proc
        if p is None:
            return
        try:
            if p.stdin:
                p.stdin.close()
        except OSError:
            pass
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=3)
        for th in self._leitores:  # processo encerrado => pipes em EOF => leitores terminam
            th.join(timeout=2)
        for fluxo in (p.stdout, p.stderr):  # sem isto cada execucao vaza descritores de arquivo
            try:
                if fluxo:
                    fluxo.close()
            except OSError:
                pass
        self._falhar_pendentes(AcpDesconectado("Cliente encerrado."))

    def stderr_recente(self) -> str:
        return sanitizar_texto("\n".join(self._stderr))

    # ---------------------------------------------------------------- leitura
    def _ler_stdout(self) -> None:
        assert self._proc and self._proc.stdout
        try:
            for linha in self._proc.stdout:
                linha = linha.strip()
                if not linha or len(linha) > MAX_LINHA:
                    continue
                try:
                    msg = json.loads(linha)
                except json.JSONDecodeError:
                    log.debug("linha nao-JSON ignorada em stdout")  # ruido nao deve derrubar o cliente
                    continue
                if isinstance(msg, dict):
                    self._despachar(msg)
        except (OSError, ValueError):
            pass
        finally:
            self._falhar_pendentes(AcpDesconectado("Processo ACP encerrou a conexao."))

    def _ler_stderr(self) -> None:
        assert self._proc and self._proc.stderr
        try:
            for linha in self._proc.stderr:
                self._stderr.append(linha.rstrip()[:500])
        except (OSError, ValueError):
            pass

    def _falhar_pendentes(self, exc: Exception) -> None:
        with self._mu:
            pend, self._pend = self._pend, {}
        for f in pend.values():
            if not f.done():
                f.set_exception(exc)

    def _despachar(self, msg: dict[str, Any]) -> None:
        if "method" in msg and "id" in msg:
            # Em thread propria: uma permissao pode esperar decisao humana e nao pode bloquear o leitor do protocolo.
            threading.Thread(target=self._atender_pedido, args=(msg,), name="acp-pedido", daemon=True).start()
        elif "method" in msg:
            if msg["method"] == "session/update":
                p = msg.get("params") or {}
                upd = p.get("update") or {}
                self._memorizar_tool_call(upd)
                if self._on_update:
                    try:
                        self._on_update(str(p.get("sessionId", "")), upd)
                    except Exception:  # noqa: BLE001 - callback nao pode derrubar o leitor
                        log.exception("falha em on_update")
            elif self._on_notificacao:
                try:
                    self._on_notificacao(str(msg["method"]), msg.get("params") or {})
                except Exception:  # noqa: BLE001 - callback nao pode derrubar o leitor
                    log.exception("falha em on_notificacao")
        elif "id" in msg:
            with self._mu:
                f = self._pend.pop(msg["id"], None) if isinstance(msg["id"], int) else None
            if f is None or f.done():
                return
            if "error" in msg:
                f.set_exception(_traduz_erro(msg["error"] or {}))
            else:
                f.set_result(msg.get("result") or {})

    def _memorizar_tool_call(self, upd: dict[str, Any]) -> None:
        """O pedido de permissao real traz so title/status/toolCallId; kind, rawInput e locations vem no tool_call."""
        if upd.get("sessionUpdate") not in ("tool_call", "tool_call_update"):
            return
        tid = upd.get("toolCallId")
        if not isinstance(tid, str):
            return
        with self._mu:
            atual = self._tool_calls.setdefault(tid, {})
            atual.update({k: v for k, v in upd.items() if v is not None and k != "sessionUpdate"})
            while len(self._tool_calls) > 200:
                self._tool_calls.pop(next(iter(self._tool_calls)))

    def _enriquecer(self, params: dict[str, Any]) -> dict[str, Any]:
        tc = dict(params.get("toolCall") or {})
        with self._mu:
            conhecido = dict(self._tool_calls.get(str(tc.get("toolCallId")), {}))
        return {**params, "toolCall": {**conhecido, **{k: v for k, v in tc.items() if v is not None}}}

    def _atender_pedido(self, msg: dict[str, Any]) -> None:
        """Pedidos do agente ao cliente. TODA requisicao recebe resposta (nenhuma fica pendente)."""
        metodo, rid, params = msg["method"], msg["id"], msg.get("params") or {}
        if metodo == "session/request_permission":
            params = self._enriquecer(params)
            titulo = str((params.get("toolCall") or {}).get("title", ""))
            self.permissoes_vistas.append({"titulo": sanitizar_texto(titulo)})
            try:
                escolhida = self._decisor(params)
            except Exception:  # noqa: BLE001
                log.exception("decisor de permissao falhou; negando")
                escolhida = None
            opcoes = params.get("options", [])
            tipo = next((str(o.get("kind", "")) for o in opcoes if o.get("optionId") == escolhida), "")
            if escolhida is None or tipo.startswith("reject"):
                self.permissoes_negadas += 1
            else:
                self.permissoes_aprovadas += 1
            if escolhida is None:
                self._responder(rid, {"outcome": {"outcome": "cancelled"}})
            else:
                self._responder(rid, {"outcome": {"outcome": "selected", "optionId": escolhida}})
        else:  # fs/*, terminal/*, extensoes: capacidades nao anunciadas
            self._enviar({"jsonrpc": "2.0", "id": rid,
                          "error": {"code": -32601, "message": f"Metodo nao suportado pelo cliente: {metodo}"}})

    # ---------------------------------------------------------------- escrita
    def _enviar(self, obj: dict[str, Any]) -> None:
        p = self._proc
        if p is None or p.stdin is None or p.poll() is not None:
            raise AcpDesconectado("Processo ACP nao esta ativo.")
        dados = json.dumps(obj, ensure_ascii=True) + "\n"  # escapado: independe do encoding do processo filho
        with self._escrita:
            try:
                p.stdin.write(dados)
                p.stdin.flush()
            except (OSError, ValueError) as e:
                raise AcpDesconectado("Falha ao escrever no processo ACP.") from e

    def _responder(self, rid: Any, resultado: dict[str, Any]) -> None:
        try:
            self._enviar({"jsonrpc": "2.0", "id": rid, "result": resultado})
        except AcpDesconectado:
            pass

    def requisitar(self, metodo: str, params: dict[str, Any], timeout: float = 30.0) -> Future:
        rid = next(self._ids)
        f: Future = Future()
        with self._mu:
            self._pend[rid] = f
        try:
            self._enviar({"jsonrpc": "2.0", "id": rid, "method": metodo, "params": params})
        except AcpDesconectado:
            with self._mu:
                self._pend.pop(rid, None)
            raise
        return f

    def chamar(self, metodo: str, params: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        f = self.requisitar(metodo, params)
        try:
            return f.result(timeout=timeout)
        except FuturoTimeout as e:
            raise AcpTimeout(f"Timeout aguardando {metodo} ({timeout:.0f}s).") from e

    def notificar(self, metodo: str, params: dict[str, Any]) -> None:
        self._enviar({"jsonrpc": "2.0", "method": metodo, "params": params})

    # ---------------------------------------------------------------- API de alto nivel
    def inicializar(self, timeout: float = 20.0) -> dict[str, Any]:
        res = self.chamar("initialize", {
            "protocolVersion": PROTOCOLO,
            "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
            "clientInfo": {"name": "forja", "title": "Forja", "version": "0.2.0"},
        }, timeout)
        versao = res.get("protocolVersion")
        if versao != PROTOCOLO:
            raise AcpProtocoloNaoSuportado(f"Versao de protocolo ACP nao suportada: {versao!r}.")
        self.agent_info = res.get("agentInfo") or {}
        self.capacidades = res.get("agentCapabilities") or {}
        self.auth_methods = [
            {"id": m.get("id"), "name": m.get("name")} for m in (res.get("authMethods") or []) if isinstance(m, dict)
        ]
        return res

    def nova_sessao(self, cwd: str, timeout: float = 30.0, mcp_servers: list[dict[str, Any]] | None = None, presets: list[str] | None = None) -> str:
        params: dict[str, Any] = {"cwd": cwd, "mcpServers": mcp_servers or []}
        if presets:
            params["_meta"] = {"kiro": {"policyPreset": list(presets)}}  # presets de permissao do Kiro (so "allow"; deny do perfil vence)
        res = self.chamar("session/new", params, timeout)
        sid = res.get("sessionId")
        if not isinstance(sid, str) or not sid:
            raise AcpErro("Resposta de session/new sem sessionId.")
        self.opcoes_sessao = [o for o in res.get("configOptions") or [] if isinstance(o, dict)]
        return sid

    @property
    def suporta_carregar_sessao(self) -> bool:
        return self.capacidades.get("loadSession") is True

    def carregar_sessao(self, session_id: str, cwd: str, timeout: float = 30.0, mcp_servers: list[dict[str, Any]] | None = None,
                        presets: list[str] | None = None) -> str:
        """session/load: reabre uma sessao anterior (o agente reenvia o historico como notificacoes ANTES da resposta).
        So deve ser chamado se o agente anunciou loadSession; o chamador decide o que fazer com as notificacoes de replay."""
        if not self.suporta_carregar_sessao:
            raise AcpMetodoNaoSuportado("O agente nao anunciou loadSession.")
        params: dict[str, Any] = {"sessionId": session_id, "cwd": cwd, "mcpServers": mcp_servers or []}
        if presets:
            params["_meta"] = {"kiro": {"policyPreset": list(presets)}}
        res = self.chamar("session/load", params, timeout)
        self.opcoes_sessao = [o for o in res.get("configOptions") or [] if isinstance(o, dict)]
        return session_id

    def modos(self) -> list[str]:
        """Modos (agentes) oferecidos pela sessao atual; perfis em ~/.kiro/agents aparecem aqui."""
        for o in self.opcoes_sessao:
            if o.get("id") == "mode":
                return [str(v.get("value")) for v in o.get("options") or [] if isinstance(v, dict)]
        return []

    def definir_opcao(self, session_id: str, config_id: str, valor: str, timeout: float = 20.0) -> list[dict[str, Any]]:
        """`session/set_config_option`: devolve a lista de opcoes ATUALIZADA (algumas so existem apos outra escolha)."""
        res = self.chamar("session/set_config_option", {"sessionId": session_id, "configId": config_id, "value": valor}, timeout)
        self.opcoes_sessao = [o for o in res.get("configOptions") or [] if isinstance(o, dict)]
        return self.opcoes_sessao

    def cancelar(self, session_id: str) -> None:
        try:
            self.notificar("session/cancel", {"sessionId": session_id})
        except AcpDesconectado:
            pass
