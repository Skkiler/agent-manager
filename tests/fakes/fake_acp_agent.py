"""Agente ACP FALSO para testes (subprocesso real, protocolo JSON-RPC por linhas). Nao e o Kiro.

Uso: python fake_acp_agent.py <cenario>
Cenarios: ok | auth | permissao | lento | crash | ruido | protocolo | vazio | recusa | longo | init_travado
"""

from __future__ import annotations

import json
import sys
import time

sys.stdin.reconfigure(encoding="utf-8")
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
        elif cenario in ("multiplas", "repetida"):
            n_prompt = globals().get("n_prompt", 0) + 1
            globals()["n_prompt"] = n_prompt
            if n_prompt > 1:  # turno de acompanhamento com adendos do operador
                txt = ((msg.get("params") or {}).get("prompt") or [{}])[0].get("text", "")
                chunk(sid, f"acompanhamento recebido: {txt[-120:]!r}")
                enviar({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
                continue
            if cenario == "multiplas":
                # 3 ferramentas pedidas AO MESMO TEMPO; formato real: o pedido so traz title/status/toolCallId
                defs = [("910", "Write File", "edit", {"path": "src/a.py", "text": "x"}),
                        ("911", "Run command", "execute", {"command": "rm -rf build dist"}),
                        ("912", "Read File", "read", {"path": ".env"})]
            else:
                defs = [("920", "Write File", "edit", {"path": "src/a.py", "text": "x"})]
            for tid, titulo, kind, raw in defs:
                update(sid, {"sessionUpdate": "tool_call", "toolCallId": tid, "title": titulo, "kind": kind,
                             "rawInput": raw, "status": "pending"})
            opcoes = [{"optionId": "accept", "name": "Permitir", "kind": "allow_once"},
                      {"optionId": "always-accept", "name": "Sempre", "kind": "allow_always"},
                      {"optionId": "reject", "name": "Negar", "kind": "reject_once"},
                      {"optionId": "always-reject", "name": "Nunca", "kind": "reject_always"}]
            for tid, titulo, _k, _r in defs:
                enviar({"jsonrpc": "2.0", "id": int(tid), "method": "session/request_permission", "params": {
                    "sessionId": sid, "toolCall": {"toolCallId": tid, "title": titulo, "status": "pending"},
                    "options": opcoes}})
            respostas: dict[str, str] = {}
            while len(respostas) < len(defs):
                r = ler()
                if r is None:
                    sys.exit(0)
                if "result" in r and r.get("id") in {int(d[0]) for d in defs}:
                    o = r["result"]["outcome"]
                    respostas[str(r["id"])] = o.get("optionId", o["outcome"])
            if cenario == "repetida":  # mesma acao de novo: com 'lembrar', o operador NAO deve ser consultado outra vez
                update(sid, {"sessionUpdate": "tool_call", "toolCallId": "921", "title": "Write File", "kind": "edit",
                             "rawInput": {"path": "src/a.py", "text": "y"}, "status": "pending"})
                enviar({"jsonrpc": "2.0", "id": 921, "method": "session/request_permission", "params": {
                    "sessionId": sid, "toolCall": {"toolCallId": "921", "title": "Write File", "status": "pending"},
                    "options": opcoes}})
                while "921" not in respostas:
                    r = ler()
                    if r and "result" in r and r.get("id") == 921:
                        o = r["result"]["outcome"]
                        respostas["921"] = o.get("optionId", o["outcome"])
            chunk(sid, "decisoes=" + json.dumps(respostas, sort_keys=True))
            enviar({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
        elif cenario == "eco":  # devolve o prompt recebido: permite provar o que foi (e o que NAO foi) enviado ao modelo
            txt = ((msg.get("params") or {}).get("prompt") or [{}])[0].get("text", "")
            chunk(sid, "## Resposta\n<<PROMPT>>\n" + txt + "\n<<FIM>>")
            enviar({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
        elif cenario in ("briefing", "briefing_sem_decisao", "briefing_longo"):
            n_prompt = globals().get("n_prompt", 0) + 1
            globals()["n_prompt"] = n_prompt
            txt = ((msg.get("params") or {}).get("prompt") or [{}])[0].get("text", "")
            globals().setdefault("prompts_recebidos", []).append(txt)
            if "Retomada da conversa" in txt:  # 2a rodada: o desenvolvedor ja respondeu
                chunk(sid, "## Entendimento\nVoce decidiu usar Bearer.\n\n## Resposta\nSeguindo sua decisao, o plano esta fechado "
                           f"(recebi {len(txt)} caracteres de contexto). Veja [M1].\n\n## Decisões para você\nNenhuma decisão necessária.\n")
            elif cenario == "briefing_longo":
                chunk(sid, "## Resposta\n" + ("detalhe tecnico relevante. " * 400))  # > 2000 caracteres: nao pode truncar
            elif cenario == "briefing_sem_decisao":
                chunk(sid, "## Entendimento\nPedido claro.\n\n## Resposta\nFeito. Conforme [M1], use integrity_check.\n\n"
                           "## Premissas\n- Python 3.12\n\n## Decisões para você\nNenhuma.\n\n## Próximos passos\n- Rodar os testes\n")
            else:
                chunk(sid, f"## Entendimento\nVoce quer escolher a autenticacao da API (prompt de {len(txt)} caracteres).\n\n"
                           "## Resposta\nPosso seguir com duas opcoes.\n\n"
                           "## Decisões para você\n1. Usar token Bearer ou cookie? — Recomendo: Bearer (mais simples). Alternativas: cookie\n"
                           "2. Publicar agora? — Recomendo: depois da revisao.\n\n## Próximos passos\n- Implementar o servico\n")
            enviar({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
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
