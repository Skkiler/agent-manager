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


_ESCRITA = __import__("threading").Lock()


def enviar(o: dict) -> None:
    with _ESCRITA:
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
escolha: dict = {}
MODELOS = ["auto", "claude-haiku-5.5", "claude-opus-5.5", "deepseek-3.2"]


def opcoes_modelos() -> list[dict]:
    """Esforco so existe para modelos claude-* (como no agente real)."""
    ops = [{"type": "select", "id": "model", "currentValue": escolha.get("model", "auto"),
            "options": [{"value": v, "name": v} for v in MODELOS]}]
    if str(escolha.get("model", "")).startswith("claude"):
        ops.append({"type": "select", "id": "effortLevel", "currentValue": escolha.get("effortLevel", "medium"),
                    "options": [{"value": v, "name": v} for v in ("low", "medium", "high", "xhigh", "max")]})
    return ops


def opcoes() -> list[dict]:
    """Como o kiro-cli 3.1.0: perfis de ~/.kiro/agents aparecem como modos. Cenarios '*sem_perfil*' nao oferecem 'forja'."""
    ops = opcoes_modelos() if cenario == "modelos" else []
    modos = ["vibe", "spec"] + ([] if "sem_perfil" in cenario else ["forja"])
    ops.append({"type": "select", "id": "mode", "currentValue": escolha.get("mode", "vibe"),
                "options": [{"value": v, "name": v} for v in modos]})
    return ops


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
            "protocolVersion": versao,
            "agentCapabilities": {"promptCapabilities": {"image": False}, "loadSession": cenario.startswith("carregavel")},
            "authMethods": [{"id": "kiro-login", "name": "Kiro Login"}],
            "agentInfo": {"name": "Fake ACP Agent", "version": "0.0.1"}}})
    elif m == "session/new":
        globals()["meta_recebido"] = (msg.get("params") or {}).get("_meta")
        if cenario == "auth":
            enviar({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000,
                    "message": "Authentication required. Not logged in. Run `kiro-cli login` first."}})
        elif cenario == "mcp_falha":
            globals()["mcp_recebido"] = (msg.get("params") or {}).get("mcpServers")
            enviar({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": sid, "configOptions": opcoes()}})
            enviar({"jsonrpc": "2.0", "method": "_kiro/mcp/status", "params": {"sessionId": sid, "servers": [{"name": "forja", "status": "failed"}]}})
        elif cenario in ("mcp", "mcp_mudo"):  # imita o kiro-cli 3.1.0: MCP conecta DEPOIS da resposta de session/new
            globals()["mcp_recebido"] = (msg.get("params") or {}).get("mcpServers")
            enviar({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": sid, "configOptions": opcoes()}})

            def info(tokens: int, sid: str = sid) -> None:
                update(sid, {"sessionUpdate": "session_info_update", "_meta": {"kiro": {"kind": "context_usage", "breakdown": {"tools": {"tokens": tokens}}}}})

            info(4913)
            if cenario == "mcp":
                import threading

                def conectar(sid: str = sid) -> None:  # em paralelo: um prompt enviado cedo demais chega ANTES desta marca
                    enviar({"jsonrpc": "2.0", "method": "_kiro/mcp/status", "params": {"sessionId": sid, "servers": [
                        {"name": "forja", "status": "connecting"}]}})
                    time.sleep(0.6)
                    globals()["mcp_conectado_em"] = time.monotonic()
                    # como o kiro-cli 3.1.0: o status chega antes e o 'breakdown' pode ate DIMINUIR (troca de modo)
                    enviar({"jsonrpc": "2.0", "method": "_kiro/mcp/status", "params": {"sessionId": sid, "servers": [
                        {"name": "forja", "status": "connected", "tools": [{"name": "forja_listar_ferramentas"}]}]}})
                    info(4793)

                threading.Thread(target=conectar, daemon=True).start()
        elif cenario == "modelos":  # imita o kiro-cli 3.1.0 real (engine v3)
            enviar({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": sid, "configOptions": opcoes()}})
        else:
            enviar({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": sid, "configOptions": opcoes()}})
    elif m == "session/load":
        if cenario == "carregavel_falha":
            enviar({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "Session not found"}})
        else:  # como o agente real: reenvia o historico como notificacoes ANTES da resposta
            sid = (msg.get("params") or {}).get("sessionId", sid)
            chunk(sid, "HISTORICO-REPRODUZIDO")
            update(sid, {"sessionUpdate": "tool_call", "toolCallId": "h1", "title": "Ferramenta antiga", "kind": "read", "status": "completed"})
            carregada = True
            enviar({"jsonrpc": "2.0", "id": rid, "result": {"configOptions": opcoes()}})
    elif m == "session/prompt" and cenario in ("mcp", "mcp_mudo", "mcp_falha"):
        pronto = "mcp_conectado_em" in globals()
        nomes = [s.get("name") for s in globals().get("mcp_recebido") or []]
        txt = ((msg.get("params") or {}).get("prompt") or [{}])[0].get("text", "")
        chunk(sid, f"mcp_pronto_no_prompt={pronto} servidores={nomes} dica={'forja::forja_listar_ferramentas' in txt}")
        enviar({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
    elif m == "session/prompt" and cenario.startswith("carregavel"):
        txt = ((msg.get("params") or {}).get("prompt") or [{}])[0].get("text", "")
        chunk(sid, f"sessao={sid} carregada={globals().get('carregada', False)}\n<<PROMPT>>\n{txt}\n<<FIM>>")
        enviar({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
    elif m == "session/set_config_option" and (msg.get("params") or {}).get("configId") == "mode":
        valor = (msg.get("params") or {}).get("value")
        if valor in [o["value"] for o in opcoes()[-1]["options"]]:
            escolha["mode"] = valor
            enviar({"jsonrpc": "2.0", "id": rid, "result": {"configOptions": opcoes()}})
        else:
            enviar({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "modo desconhecido"}})
    elif m == "session/prompt" and cenario.startswith("perfil"):
        chunk(sid, f"modo={escolha.get('mode', 'vibe')} meta={json.dumps(globals().get('meta_recebido'), sort_keys=True)}")
        enviar({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
    elif m == "session/set_config_option" and cenario == "modelos":
        p = msg.get("params") or {}
        if p.get("configId") == "model":
            escolha["model"] = p.get("value")  # o agente real ACEITA qualquer valor em silencio
            escolha.pop("effortLevel", None)
        elif p.get("configId") == "effortLevel" and p.get("value") in ("low", "medium", "high", "xhigh", "max"):
            escolha["effortLevel"] = p["value"]
        enviar({"jsonrpc": "2.0", "id": rid, "result": {"configOptions": opcoes()}})
    elif m == "session/prompt" and cenario == "modelos":
        chunk(sid, f"configuracao model={escolha.get('model', 'auto')} effort={escolha.get('effortLevel', '-')}")
        enviar({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
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
        elif cenario in ("corrige", "corrige_nunca"):  # 1o turno deixa um bug; ao receber a falha da Forja, corrige (ou nao)
            import os

            txt = ((msg.get("params") or {}).get("prompt") or [{}])[0].get("text", "")
            alvo = os.path.join(os.getcwd(), "soma.py")
            segunda = "FALHARAM" in txt
            correto = segunda and cenario == "corrige"
            with open(alvo, "w", encoding="utf-8") as f:
                f.write("def soma(a, b):\n    return a + b\n" if correto else "def soma(a, b):\n    return a - b\n")
            update(sid, {"sessionUpdate": "tool_call", "toolCallId": f"w{int(segunda)}", "title": "Write File", "kind": "edit",
                         "status": "completed", "rawInput": {"path": alvo}})
            chunk(sid, ("## Resposta\nCorrigi a soma.\n## Evidências\n- alterei soma.py\n" if segunda else
                        "## Resposta\nImplementei `soma.py` e os testes passaram.\n"))
            enviar({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
        elif cenario in ("laco", "muitas"):  # agente perdido: repete a mesma leitura (ou faz chamadas sem fim) ate ser cancelado
            chunk(sid, "## Resposta\nprocurando...")
            for i in range(40):
                titulo = "Read File" if cenario == "laco" else f"Read File {i}"
                update(sid, {"sessionUpdate": "tool_call", "toolCallId": f"l{i}", "title": titulo, "kind": "read", "status": "completed",
                             "rawInput": {"path": "a.py" if cenario == "laco" else f"a{i}.py"}})
                time.sleep(0.01)
            while True:
                n = ler()
                if n is None:
                    sys.exit(0)
                if n.get("method") == "session/cancel":
                    enviar({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "cancelled"}})
                    break
        elif cenario == "alegacao":  # afirma ter testado sem chamar nenhuma ferramenta (alucinacao tipica)
            update(sid, {"sessionUpdate": "tool_call", "toolCallId": "r1", "title": "Read File", "kind": "read", "status": "completed"})
            chunk(sid, "## Resposta\nCorrigi o modulo e todos os testes passaram.\n")
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
