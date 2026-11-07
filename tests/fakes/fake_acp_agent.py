"""Agente ACP FALSO para testes (subprocesso real, protocolo JSON-RPC por linhas). Nao e o Kiro.

Uso: python fake_acp_agent.py <cenario>
Cenarios: ok | auth | permissao | lento | crash | ruido | protocolo | vazio | recusa | longo | init_travado
"""

from __future__ import annotations

import json
import sys
import time

cenario = sys.argv[1] if len(sys.argv) > 1 else "ok"


def enviar(o: dict) -> None:
    sys.stdout.write(json.dumps(o) + "\n")
    sys.stdout.flush()


def ler() -> dict | None:
    linha = sys.stdin.readline()
    return json.loads(linha) if linha else None


def update(sid: str, upd: dict) -> None:
    enviar({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": sid, "update": upd}})


def chunk(sid: str, texto: str) -> None:
    update(sid, {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": texto}})


if cenario == "ruido":
    sys.stdout.write("isto nao e json\n{quebrado\n")
    sys.stdout.flush()
print("aviso de debug no stderr", file=sys.stderr, flush=True)

sid = "sess-fake-1"
while True:
    msg = ler()
    if msg is None:
        break
    m, rid = msg.get("method"), msg.get("id")
    if m == "initialize":
        if cenario == "init_travado":
            time.sleep(60)
        versao = 99 if cenario == "protocolo" else 1
        enviar({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": versao, "agentCapabilities": {"promptCapabilities": {"image": False}},
            "authMethods": [{"id": "kiro-login", "name": "Kiro Login"}],
            "agentInfo": {"name": "Fake ACP Agent", "version": "0.0.1"}}})
    elif m == "session/new":
        if cenario == "auth":
            enviar({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000,
                    "message": "Authentication required. Not logged in. Run `kiro-cli login` first."}})
        else:
            enviar({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": sid}})
    elif m == "session/prompt":
        if cenario == "crash":
            chunk(sid, "parcial")
            sys.exit(3)
        if cenario == "vazio":
            enviar({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
        elif cenario == "recusa":
            enviar({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "refusal"}})
        elif cenario == "longo":
            for _ in range(5):
                chunk(sid, "x" * 100_000)
            enviar({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
        elif cenario == "lento":
            chunk(sid, "iniciando...")
            # espera cancelamento do cliente
            while True:
                n = ler()
                if n is None:
                    sys.exit(0)
                if n.get("method") == "session/cancel":
                    enviar({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "cancelled"}})
                    break
        elif cenario == "permissao":
            enviar({"jsonrpc": "2.0", "id": 900, "method": "session/request_permission", "params": {
                "sessionId": sid, "toolCall": {"toolCallId": "t1", "title": "Escrever arquivo"},
                "options": [{"optionId": "allow", "name": "Permitir", "kind": "allow_once"},
                            {"optionId": "deny", "name": "Negar", "kind": "reject_once"}]}})
            resp = ler()
            escolha = json.dumps((resp or {}).get("result"), sort_keys=True)
            # tenta capacidade nao anunciada: o cliente deve responder erro -32601 (nunca ficar pendente)
            enviar({"jsonrpc": "2.0", "id": 901, "method": "fs/read_text_file", "params": {"path": "x"}})
            resp_fs = ler()
            chunk(sid, f"permissao={escolha}; fs_erro={(resp_fs or {}).get('error', {}).get('code')}")
            enviar({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
        else:  # ok
            update(sid, {"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "Ler resumo", "kind": "read",
                         "status": "pending"})
            chunk(sid, "## Resumo\n")
            chunk(sid, "Analise concluida (agente falso). token=SEGREDO123456 deve ser redigido.")
            enviar({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
    elif m == "session/cancel":
        pass
    elif rid is not None:
        enviar({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "nao suportado"}})
