"""4.7c: MCP stdio da Forja. Protocolo, limites de seguranca e integracao com a API real (TestClient)."""

from __future__ import annotations

import io
import json
import subprocess
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from forja.mcp.servidor import FERRAMENTAS, LIMITE_SAIDA, ClienteForja, ServidorMcp, validar_url_loopback


class _PonteTestClient(httpx.BaseTransport):
    """Faz o MCP falar com a API REAL (em memoria), sem abrir porta."""

    def __init__(self, tc: TestClient) -> None:
        self.tc = tc

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        r = self.tc.request(request.method, request.url.raw_path.decode(), content=request.content,
                            headers={k: v for k, v in request.headers.items() if k.lower() in ("content-type", "authorization")})
        return httpx.Response(r.status_code, content=r.content, headers={"content-type": r.headers.get("content-type", "application/json")})


@pytest.fixture
def mcp(client: TestClient) -> ServidorMcp:
    return ServidorMcp(ClienteForja("http://127.0.0.1:8787", "token-de-teste-com-tamanho-suficiente", transporte=_PonteTestClient(client)))


def _chamar(s: ServidorMcp, nome: str, args: dict | None = None) -> dict:
    r = s.tratar({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": nome, "arguments": args}})
    return r["result"]


def _texto(r: dict) -> str:
    return r["content"][0]["text"]


# ------------------------------------------------------------------ protocolo
def test_initialize_negocia_versao_e_anuncia_so_ferramentas(mcp):
    r = mcp.tratar({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})["result"]
    assert r["protocolVersion"] == "2025-03-26" and set(r["capabilities"]) == {"tools"} and r["serverInfo"]["name"] == "forja"
    r2 = mcp.tratar({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})["result"]
    assert r2["protocolVersion"] == "2025-06-18"  # versao desconhecida: responde a que suporta


def test_notificacao_nao_tem_resposta_e_metodo_desconhecido_e_erro(mcp):
    assert mcp.tratar({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert mcp.tratar({"jsonrpc": "2.0", "id": 5, "method": "resources/list"})["error"]["code"] == -32601
    assert mcp.tratar([1, 2])["error"]["code"] == -32600
    assert mcp.tratar({"jsonrpc": "1.0", "id": 1, "method": "ping"})["error"]["code"] == -32600
    assert mcp.tratar({"jsonrpc": "2.0", "id": 7, "method": "ping"})["result"] == {}


def test_lista_poucas_ferramentas_com_descricao_curta(mcp):
    ts = mcp.tratar({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    assert {t["name"] for t in ts} == set(FERRAMENTAS) and len(ts) == 5
    assert all(len(t["description"]) < 200 and t["inputSchema"]["additionalProperties"] is False for t in ts)
    assert len(json.dumps(ts)) < 4500  # custo fixo por sessao: mantido pequeno de proposito


def test_loop_stdio_ignora_linhas_vazias_e_responde_json_invalido():
    s = ServidorMcp(ClienteForja("http://127.0.0.1:1", None))
    entrada = io.StringIO('\n{quebrado\n{"jsonrpc":"2.0","id":3,"method":"ping"}\n')
    saida = io.StringIO()
    s.servir(entrada, saida)
    linhas = [json.loads(x) for x in saida.getvalue().splitlines()]
    assert linhas[0]["error"]["code"] == -32700 and linhas[1] == {"jsonrpc": "2.0", "id": 3, "result": {}}


# ------------------------------------------------------------------ seguranca
@pytest.mark.parametrize("url", ["https://127.0.0.1:8787", "http://192.168.0.10:8787", "http://exemplo.com", "http://user:senha@127.0.0.1",
                                 "ftp://127.0.0.1", "http://0.0.0.0:8787"])
def test_so_aceita_loopback(url):
    with pytest.raises(ValueError):
        validar_url_loopback(url)


def test_loopback_aceito():
    assert validar_url_loopback("http://127.0.0.1:8787/") == "http://127.0.0.1:8787"
    assert validar_url_loopback("http://localhost:1") == "http://localhost:1"


def test_processo_recusa_url_fora_do_loopback():
    r = subprocess.run([sys.executable, "-m", "forja.mcp"], input="", capture_output=True, text=True, timeout=60,
                       env={**__import__("os").environ, "FORJA_MCP_URL": "http://10.0.0.5:8787", "APP_REQUIRE_AUTH": "false"})
    assert r.returncode == 2 and "127.0.0.1" in r.stderr


def test_processo_real_responde_initialize_por_stdio():
    msgs = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}\n{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
    r = subprocess.run([sys.executable, "-m", "forja.mcp"], input=msgs, capture_output=True, text=True, timeout=60,
                       env={**__import__("os").environ, "FORJA_MCP_URL": "http://127.0.0.1:9", "APP_REQUIRE_AUTH": "false"})
    saidas = [json.loads(x) for x in r.stdout.splitlines()]
    assert saidas[0]["result"]["serverInfo"]["name"] == "forja" and len(saidas[1]["result"]["tools"]) == 5


def test_agente_nao_envia_comando_nem_escolhe_origem(mcp):
    r = _chamar(mcp, "forja_quadro_publicar", {"tipo": "comando", "assunto": "x"})
    assert r["isError"] and "comandos" in _texto(r)
    r = _chamar(mcp, "forja_quadro_publicar", {"tipo": "evento", "assunto": "x", "destino": "agente:outro"})
    assert r["isError"]
    r = _chamar(mcp, "forja_quadro_publicar", {"tipo": "evento", "assunto": "x", "origem": "master"})  # campo extra e ignorado: origem e fixa
    assert not r["isError"] and json.loads(_texto(r))["origem"] == "agente:kiro"


def test_id_de_ferramenta_com_caminho_e_recusado(mcp):
    for ruim in ("../x", "a/b", "", "a b", "x" * 200, None):
        assert _chamar(mcp, "forja_executar_ferramenta", {"id": ruim})["isError"]


def test_argumentos_invalidos_nao_derrubam(mcp):
    assert _chamar(mcp, "forja_buscar_memoria", {"consulta": ""})["isError"]
    assert _chamar(mcp, "forja_buscar_memoria", {"consulta": "x", "limite": 999})["isError"]
    assert _chamar(mcp, "forja_buscar_memoria", {"consulta": "x", "limite": True})["isError"]
    assert _chamar(mcp, "forja_quadro_ler", {"limite": 0})["isError"]
    assert _chamar(mcp, "forja_inexistente")["isError"]
    r = mcp.tratar({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "forja_listar_ferramentas", "arguments": "texto"}})["result"]
    assert r["isError"]


def test_api_indisponivel_vira_erro_amigavel_sem_detalhes_internos():
    s = ServidorMcp(ClienteForja("http://127.0.0.1:9", None, timeout=1))
    r = _chamar(s, "forja_listar_ferramentas")
    assert r["isError"] and "Forja" in _texto(r) and "Traceback" not in _texto(r)


def test_saida_longa_e_cortada_e_segredo_redigido():
    def transporte(request):
        return httpx.Response(200, json={"dados": "x" * 50_000, "token": "SEGREDO-1234567890-ABCDEFG"})

    s = ServidorMcp(ClienteForja("http://127.0.0.1:1", None, transporte=httpx.MockTransport(transporte)))
    s.cliente.chamar = lambda *a, **k: {"dados": "x" * 50_000, "api_key": "sk-abcdefghijklmnopqrstuvwxyz0123456789"}  # type: ignore[method-assign]
    r = _chamar(s, "forja_executar_ferramenta", {"id": "repo.mapa"})
    t = _texto(r)
    assert len(t) <= LIMITE_SAIDA + 80 and "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in t


# ------------------------------------------------------------------ integracao com a API real
def test_lista_so_ferramentas_disponiveis(mcp, client):
    ids = {f["id"] for f in json.loads(_texto(_chamar(mcp, "forja_listar_ferramentas")))}
    todas = {f["id"] for f in client.get("/api/v1/ferramentas").json() if f["disponivel"]}
    assert ids == todas and ids  # integracoes de rede desligadas nao aparecem


def test_executa_ferramenta_real_e_o_servidor_ainda_decide(mcp):
    r = _chamar(mcp, "forja_executar_ferramenta", {"id": "testes.resumir_saida", "entrada": {"texto": "===== 1 passed in 0.10s ====="}})
    assert not r["isError"]
    r = _chamar(mcp, "forja_executar_ferramenta", {"id": "repo.mapa", "entrada": {"caminho": "C:/"}})
    assert r["isError"]  # leitura de arquivos desligada por padrao: a API recusa, o MCP nao contorna
    assert _chamar(mcp, "forja_executar_ferramenta", {"id": "nao.existe"})["isError"]


def test_publica_e_le_no_quadro(mcp, client):
    r = _chamar(mcp, "forja_quadro_publicar", {"tipo": "pergunta", "assunto": "Posso publicar?", "prioridade": 2, "dedup_key": "k1"})
    msg = json.loads(_texto(r))
    assert msg["origem"] == "agente:kiro" and msg["destino"] == "master" and msg["prioridade"] == 2
    de_novo = json.loads(_texto(_chamar(mcp, "forja_quadro_publicar", {"tipo": "pergunta", "assunto": "Posso publicar?", "dedup_key": "k1"})))
    assert de_novo["id"] == msg["id"]  # idempotente
    assert json.loads(_texto(_chamar(mcp, "forja_quadro_ler"))) == []  # nada enderecado a este agente


def test_busca_na_memoria_passa_pela_api(mcp):
    r = _chamar(mcp, "forja_buscar_memoria", {"consulta": "autenticacao", "limite": 3})
    assert not r["isError"]


# ------------------------------------------------------------------ defesas proprias do MCP (sem depender da API recusar)
def _mcp_contando():
    vistos: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        vistos.append(req)
        return httpx.Response(200, json={"itens": ["x" * 100 for _ in range(190)]})  # ~19 mil caracteres mesmo apos sanitizar

    return ServidorMcp(ClienteForja("http://127.0.0.1:1", None, transporte=httpx.MockTransport(h))), vistos


def test_entradas_invalidas_sao_barradas_no_mcp_sem_nenhuma_requisicao():
    s, vistos = _mcp_contando()
    for ruim in ("../x", "a/b", "a b", "x" * 200, "%2e%2e"):
        assert _chamar(s, "forja_executar_ferramenta", {"id": ruim})["isError"]
    for limite in (0, 21, True, "5"):
        assert _chamar(s, "forja_buscar_memoria", {"consulta": "x", "limite": limite})["isError"]
        assert _chamar(s, "forja_quadro_ler", {"limite": limite})["isError"]
    assert vistos == []


def test_saida_grande_e_cortada_no_limite():
    s, vistos = _mcp_contando()
    t = _texto(_chamar(s, "forja_executar_ferramenta", {"id": "repo.mapa"}))
    assert len(vistos) == 1 and len(t) <= LIMITE_SAIDA + 80 and t.endswith("caracteres]")
