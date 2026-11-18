"""Bancada do painel (editor, problemas, busca, Git, terminal, Docker, HTTP) pela API. Dados sinteticos em pasta temporaria.

Politica (ADR-026): o USUARIO pode ler e editar segredos e fazer tudo no Git/Docker/terminal; acao perigosa vira pergunta (428),
nunca bloqueio. Os bloqueios de segredo valem so para os agentes externos (ver test_area_nao_vaza_para_agentes)."""

from __future__ import annotations

import http.server
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from forja.orquestracao.area_trabalho import ambiente_usuario, linguagem_de

A = "/api/v1/area"


@pytest.fixture
def proj(client, tmp_path: Path):
    trab, cons = tmp_path / "trab", tmp_path / "cons"
    trab.mkdir()
    cons.mkdir()
    (trab / "app.py").write_text("import os\nx = 1\n", encoding="utf-8")
    (trab / "d.json").write_text("{ruim", encoding="utf-8")
    (trab / ".env").write_text("SENHA=sintetica\n", encoding="utf-8")
    (trab / "bin.dat").write_bytes(b"\x00\x01\x02")
    (cons / "ref.md").write_text("# referencia\n", encoding="utf-8")
    p = client.post("/api/v1/projetos", json={"nome": f"area-{tmp_path.name}"}).json()
    r = client.put(f"/api/v1/projetos/{p['id']}/pastas", json={"expected_version": 1, "pastas": [
        {"caminho": str(trab), "papel": "trabalho"}, {"caminho": str(cons), "papel": "consulta"}]})
    assert r.status_code == 200, r.text
    return p["id"], trab, cons


def _git_init(pasta: Path) -> None:
    for args in (["init", "-q", "-b", "main"], ["config", "user.name", "Teste"], ["config", "user.email", "teste@exemplo.invalid"]):
        subprocess.run(["git", *args], cwd=pasta, check=True, capture_output=True)  # noqa: S603, S607


# ------------------------------------------------------------------ arquivos
def test_ler_e_salvar_com_concorrencia_otimista(client, proj):
    pid, trab, _ = proj
    a = client.get(f"{A}/arquivo", params={"projeto": pid, "rel": "app.py"}).json()
    assert a["linguagem"] == "python" and a["somente_leitura"] is False and len(a["sha"]) == 64 and a["segredo"] is False
    ok = client.put(f"{A}/arquivo", json={"projeto": pid, "raiz": 0, "rel": "app.py", "conteudo": "x = 2\n", "sha": a["sha"]})
    assert ok.status_code == 200 and (trab / "app.py").read_text(encoding="utf-8") == "x = 2\n"
    conflito = client.put(f"{A}/arquivo", json={"projeto": pid, "raiz": 0, "rel": "app.py", "conteudo": "x = 3\n", "sha": a["sha"]})
    assert conflito.status_code == 409 and (trab / "app.py").read_text(encoding="utf-8") == "x = 2\n"
    novo = client.put(f"{A}/arquivo", json={"projeto": pid, "raiz": 0, "rel": "src/novo.py", "conteudo": "y = 1\n"})
    assert novo.status_code == 200 and (trab / "src" / "novo.py").is_file()
    assert not list(trab.rglob("*.forja.tmp"))


def test_usuario_le_e_edita_segredo_marcado(client, proj):
    pid, trab, _ = proj
    env = client.get(f"{A}/arquivo", params={"projeto": pid, "rel": ".env"}).json()
    assert env["segredo"] is True and env["conteudo"].strip() == "SENHA=sintetica" and env["linguagem"] == "ini"
    r = client.put(f"{A}/arquivo", json={"projeto": pid, "raiz": 0, "rel": ".env", "conteudo": "SENHA=outra\n", "sha": env["sha"]})
    assert r.status_code == 200 and (trab / ".env").read_text(encoding="utf-8") == "SENHA=outra\n"
    arvore = client.get(f"{A}/arvore", params={"projeto": pid}).json()["itens"]
    assert next(i for i in arvore if i["nome"] == ".env")["segredo"] is True


def test_area_nao_vaza_para_agentes(client, proj):
    """O explorador dos AGENTES (@mencao e anexos) continua escondendo segredo; anexar .env continua recusado."""
    pid, _, _ = proj
    lista = client.get(f"/api/v1/projetos/{pid}/arquivos").json()["itens"]
    assert ".env" not in [i["nome"] for i in lista]
    assert ".env" not in [i["nome"] for i in client.get(f"/api/v1/projetos/{pid}/buscar-arquivos", params={"q": "env"}).json()]


def test_binario_e_fuga_sao_recusados(client, proj):
    pid, _, _ = proj
    assert client.get(f"{A}/arquivo", params={"projeto": pid, "rel": "bin.dat"}).status_code == 422
    assert client.get(f"{A}/arquivo", params={"projeto": pid, "rel": "../cons/ref.md"}).status_code in (403, 422)


def test_pasta_de_consulta_e_somente_leitura(client, proj):
    pid, _, cons = proj
    a = client.get(f"{A}/arquivo", params={"projeto": pid, "rel": "ref.md", "raiz": 1}).json()
    assert a["somente_leitura"] is True and a["linguagem"] == "markdown"
    r = client.put(f"{A}/arquivo", json={"projeto": pid, "raiz": 1, "rel": "ref.md", "conteudo": "mudou", "sha": a["sha"]})
    assert r.status_code == 422 and "CONSULTA" in r.text
    assert (cons / "ref.md").read_text(encoding="utf-8") == "# referencia\n"
    assert client.post(f"{A}/terminal", json={"projeto": pid, "raiz": 1, "comando": "echo oi"}).status_code == 422


def test_problemas_json_e_python(client, proj):
    pid, _, _ = proj
    j = client.post(f"{A}/problemas", json={"projeto": pid, "raiz": 0, "rel": "d.json"}).json()
    assert j["problemas"] and j["problemas"][0]["codigo"] == "json" and j["problemas"][0]["linha"] == 1
    py = client.post(f"{A}/problemas", json={"projeto": pid, "raiz": 0, "rel": "app.py", "conteudo": "def f(:\n"}).json()
    assert any(p["codigo"] == "sintaxe" for p in py["problemas"])
    assert client.post(f"{A}/problemas", json={"projeto": pid, "raiz": 0, "rel": "d.json", "conteudo": "{}"}).json()["problemas"] == []


def test_busca_pula_segredo_por_padrao_e_inclui_se_pedido(client, proj):
    pid, _, _ = proj
    r = client.get(f"{A}/buscar", params={"projeto": pid, "padrao": "SENHA"}).json()
    assert r["ocorrencias"] == [] and r["segredos_pulados"] >= 1
    r = client.get(f"{A}/buscar", params={"projeto": pid, "padrao": "SENHA", "segredos": "true"}).json()
    assert [o["arquivo"] for o in r["ocorrencias"]] == [".env"]


def test_simbolos_e_definicao(client, proj):
    pid, trab, _ = proj
    (trab / "mod.py").write_text("class Fila:\n    def poe(self):\n        pass\n\n\ndef criar():\n    return Fila()\n", encoding="utf-8")
    nomes = [s["nome"] for s in client.get(f"{A}/simbolos", params={"projeto": pid, "rel": "mod.py"}).json()["simbolos"]]
    assert "Fila" in nomes and "criar" in nomes
    d = client.get(f"{A}/definicao", params={"projeto": pid, "nome": "criar"}).json()["definicoes"]
    assert d and d[0]["caminho"] == "mod.py" and d[0]["linha"] == 6


# ------------------------------------------------------------------ Git
@pytest.mark.skipif(not shutil.which("git"), reason="git ausente")
def test_git_completo_com_confirmacao_para_segredo_e_push(client, proj, tmp_path):
    pid, trab, _ = proj
    _git_init(trab)
    st = client.get(f"{A}/git", params={"projeto": pid}).json()["dados"]
    assert st["repositorio"] and st["branch"] == "main" and any(i["arquivo"] == ".env" and i["segredo"] for i in st["alterados"])
    ex = lambda args, c=False: client.post(f"{A}/git/executar", json={"projeto": pid, "raiz": 0, "args": args, "confirmado": c})  # noqa: E731
    pergunta = ex(["add", "-A"])
    assert pergunta.status_code == 428 and ".env" in json.dumps(pergunta.json()["dados"]["motivos"])
    assert ex(["add", "app.py"]).json()["codigo"] == 0  # sem segredo: segue sem perguntar
    assert ex(["commit", "-m", "primeiro"]).json()["codigo"] == 0
    assert ex(["add", ".env"], True).json()["codigo"] == 0  # o usuario confirmou: a Forja obedece
    assert ex(["commit", "-m", "com segredo"]).status_code == 428
    assert ex(["restore", "--staged", ".env"]).json()["codigo"] == 0
    assert ex(["switch", "-c", "feature/x"]).json()["codigo"] == 0
    assert client.get(f"{A}/git", params={"projeto": pid}).json()["dados"]["branch"] == "feature/x"
    remoto = tmp_path / "remoto.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remoto)], check=True, capture_output=True)  # noqa: S603, S607
    assert ex(["remote", "add", "origin", str(remoto)]).json()["codigo"] == 0
    assert ex(["push", "-u", "origin", "feature/x"]).status_code == 428  # push sempre pergunta
    push = ex(["push", "-u", "origin", "feature/x"], True).json()
    assert push["codigo"] == 0, push
    st = client.get(f"{A}/git", params={"projeto": pid}).json()["dados"]
    assert st["remotos"] == {"origin": str(remoto)} and "feature/x" in st["branches"]
    v = client.get(f"{A}/git/versao", params={"projeto": pid, "rel": "app.py", "versao": "HEAD"}).json()
    assert v["existe"] and "x = 1" in v["conteudo"]
    assert client.post(f"{A}/git", json={"projeto": pid, "raiz": 0, "acao": "discard", "arquivos": ["app.py"]}).status_code == 428


@pytest.mark.skipif(not shutil.which("git"), reason="git ausente")
def test_git_em_pasta_de_consulta_so_le(client, proj):
    pid, _, cons = proj
    _git_init(cons)
    assert client.post(f"{A}/git/executar", json={"projeto": pid, "raiz": 1, "args": ["status"]}).json()["codigo"] == 0
    assert client.post(f"{A}/git/executar", json={"projeto": pid, "raiz": 1, "args": ["add", "."]}).status_code == 422


def test_pasta_sem_git_nao_e_erro_no_status(client, proj):
    pid, _, _ = proj
    r = client.get(f"{A}/git", params={"projeto": pid})
    assert r.status_code == 200 and r.json()["dados"]["repositorio"] is False


# ------------------------------------------------------------------ terminal
def test_terminal_roda_avisa_segredo_e_pergunta_no_perigoso(client, proj):
    pid, trab, _ = proj
    ok = client.post(f"{A}/terminal", json={"projeto": pid, "raiz": 0, "comando": "echo forja-ok"})
    assert ok.status_code == 200 and "forja-ok" in ok.json()["saida"] and ok.json()["codigo"] == 0
    env = client.post(f"{A}/terminal", json={"projeto": pid, "raiz": 0, "comando": "Get-Content .env" if shutil.which("powershell") else "cat .env"}).json()
    assert "SENHA=sintetica" in env["saida"] and any("só para você" in a for a in env["avisos"])
    (trab / "lixo").mkdir()
    perigo = client.post(f"{A}/terminal", json={"projeto": pid, "raiz": 0, "comando": "Remove-Item -Recurse lixo"})
    assert perigo.status_code == 428 and perigo.json()["dados"]["risco"] == "alto" and (trab / "lixo").exists()


def test_terminal_desligado_pela_preferencia(client, proj):
    pid, _, _ = proj
    client.app.state.area.terminal_ativo = False
    r = client.post(f"{A}/terminal", json={"projeto": pid, "raiz": 0, "comando": "echo oi"})
    assert r.status_code == 422 and "desligado" in r.text


def test_ambiente_do_usuario_sem_configuracao_interna(monkeypatch):
    monkeypatch.setenv("APP_API_TOKEN", "x")
    monkeypatch.setenv("FORJA_INT_GITHUB_TOKEN", "y")
    monkeypatch.setenv("GITHUB_TOKEN_DO_USUARIO", "z")
    env = ambiente_usuario()
    assert "APP_API_TOKEN" not in env and "FORJA_INT_GITHUB_TOKEN" not in env and env["GITHUB_TOKEN_DO_USUARIO"] == "z"


# ------------------------------------------------------------------ Docker
def test_docker_ausente_e_interativo(client, monkeypatch):
    monkeypatch.setattr("forja.orquestracao.area_trabalho.shutil.which", lambda _n: None)
    r = client.get(f"{A}/docker")
    assert r.status_code == 422 and "Docker" in r.text
    assert client.get(f"{A}/docker", params={"recurso": "xyz"}).status_code == 422
    it = client.post(f"{A}/docker/executar", json={"args": ["exec", "-it", "web", "sh"]})
    assert it.status_code == 422 and "interativo" in it.text
    assert client.post(f"{A}/docker/executar", json={"args": ["system", "prune", "-a"]}).status_code == 428
    sem = client.post(f"{A}/docker/executar", json={"args": ["ps"]}).json()
    assert sem["codigo"] == -1 and "Docker" in sem["erro"]


# ------------------------------------------------------------------ HTTP (estilo Postman)
class _Eco(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        corpo = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"recebido": json.loads(corpo), "cabecalho": self.headers.get("X-Teste")}).encode())

    def log_message(self, *a):  # silencio nos testes
        pass


def test_cliente_http_envia_e_mostra_resposta(client):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Eco)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/itens"
        r = client.post(f"{A}/http", json={"metodo": "POST", "url": url, "cabecalhos": {"X-Teste": "ok", "Content-Type": "application/json"},
                                           "corpo": json.dumps({"a": 1})}).json()
        assert r["status"] == 201 and json.loads(r["corpo"]) == {"recebido": {"a": 1}, "cabecalho": "ok"} and r["tempo_ms"] >= 0
        assert ["content-type", "application/json"] in r["cabecalhos"]
    finally:
        srv.shutdown()
        srv.server_close()
    assert client.post(f"{A}/http", json={"url": "ftp://exemplo.invalid/x"}).status_code == 422
    falha = client.post(f"{A}/http", json={"url": "http://127.0.0.1:9/nada", "tempo_s": 2}).json()
    assert falha["status"] == 0 and falha["erro"]


def test_linguagem_de():
    assert linguagem_de("Dockerfile") == "docker" and linguagem_de("a.TSX") == "typescript" and linguagem_de("x.zzz") == "texto"
    assert linguagem_de(".env.local") == "ini"


def test_quadro_usa_rotulos_acentuados(client):
    rotulos = {c["id"]: c["rotulo"] for c in client.get("/api/v1/kanban").json()["colunas"]}
    assert rotulos["executando"] == "Em execução" and rotulos["atencao"] == "Precisa de você" and rotulos["concluida"] == "Concluída"
