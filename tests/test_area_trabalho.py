"""Area de trabalho do painel (editor, problemas, busca, Git, terminal, Docker) pela API. Dados sinteticos em pasta temporaria."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from forja.orquestracao.area_trabalho import linguagem_de

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


def test_ler_e_salvar_com_concorrencia_otimista(client, proj):
    pid, trab, _ = proj
    a = client.get(f"{A}/arquivo", params={"projeto": pid, "rel": "app.py"}).json()
    assert a["linguagem"] == "python" and a["somente_leitura"] is False and len(a["sha"]) == 64
    ok = client.put(f"{A}/arquivo", json={"projeto": pid, "raiz": 0, "rel": "app.py", "conteudo": "x = 2\n", "sha": a["sha"]})
    assert ok.status_code == 200 and (trab / "app.py").read_text(encoding="utf-8") == "x = 2\n"
    conflito = client.put(f"{A}/arquivo", json={"projeto": pid, "raiz": 0, "rel": "app.py", "conteudo": "x = 3\n", "sha": a["sha"]})
    assert conflito.status_code == 409 and (trab / "app.py").read_text(encoding="utf-8") == "x = 2\n"
    novo = client.put(f"{A}/arquivo", json={"projeto": pid, "raiz": 0, "rel": "src/novo.py", "conteudo": "y = 1\n"})
    assert novo.status_code == 200 and (trab / "src" / "novo.py").is_file()
    assert not list(trab.rglob("*.forja.tmp"))


def test_segredo_binario_e_fuga_sao_recusados(client, proj):
    pid, trab, _ = proj
    assert client.get(f"{A}/arquivo", params={"projeto": pid, "rel": ".env"}).status_code == 422
    assert client.put(f"{A}/arquivo", json={"projeto": pid, "raiz": 0, "rel": ".env", "conteudo": "X=1"}).status_code == 422
    assert (trab / ".env").read_text(encoding="utf-8") == "SENHA=sintetica\n"
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
    ok = client.post(f"{A}/problemas", json={"projeto": pid, "raiz": 0, "rel": "d.json", "conteudo": "{}"}).json()
    assert ok["problemas"] == []


def test_busca_nao_olha_segredo(client, proj):
    pid, _, _ = proj
    r = client.get(f"{A}/buscar", params={"projeto": pid, "padrao": "SENHA"}).json()
    assert r["ocorrencias"] == []
    r = client.get(f"{A}/buscar", params={"projeto": pid, "padrao": "import"}).json()
    assert r["arquivos"] == 1


@pytest.mark.skipif(not shutil.which("git"), reason="git ausente")
def test_git_status_stage_e_commit_sem_segredo(client, proj):
    pid, trab, _ = proj
    for args in (["init", "-q"], ["config", "user.name", "Teste"], ["config", "user.email", "teste@exemplo.invalid"]):
        subprocess.run(["git", *args], cwd=trab, check=True, capture_output=True)  # noqa: S603, S607
    st = client.get(f"{A}/git", params={"projeto": pid}).json()
    assert ".env" not in str(st["dados"])
    r = client.post(f"{A}/git", json={"projeto": pid, "raiz": 0, "acao": "stage", "arquivos": [".env"]})
    assert r.status_code == 422
    assert client.post(f"{A}/git", json={"projeto": pid, "raiz": 0, "acao": "stage", "arquivos": ["app.py"]}).status_code == 200
    assert client.post(f"{A}/git", json={"projeto": pid, "raiz": 0, "acao": "commit", "mensagem": ""}).status_code == 422
    c = client.post(f"{A}/git", json={"projeto": pid, "raiz": 0, "acao": "commit", "mensagem": "primeiro"})
    assert c.status_code == 200, c.text
    log = subprocess.run(["git", "show", "--name-only", "--format=%s"], cwd=trab, capture_output=True, text=True, check=True)  # noqa: S603, S607
    assert "app.py" in log.stdout and ".env" not in log.stdout
    assert client.post(f"{A}/git", json={"projeto": pid, "raiz": 0, "acao": "push"}).status_code == 422


def test_terminal_recusa_segredo_e_roda_comando_simples(client, proj):
    pid, _, _ = proj
    for cmd in ("type .env", "Get-Content .env", "cat .env", "Get-ChildItem Env:"):
        r = client.post(f"{A}/terminal", json={"projeto": pid, "raiz": 0, "comando": cmd})
        assert r.status_code == 422, cmd
    r = client.post(f"{A}/terminal", json={"projeto": pid, "raiz": 0, "comando": "echo forja-ok"})
    assert r.status_code == 200, r.text
    assert "forja-ok" in r.json()["saida"] and r.json()["codigo"] == 0


def test_terminal_desligado_pela_preferencia(client, proj):
    pid, _, _ = proj
    client.app.state.area.terminal_ativo = False
    r = client.post(f"{A}/terminal", json={"projeto": pid, "raiz": 0, "comando": "echo oi"})
    assert r.status_code == 422 and "desligado" in r.text


def test_docker_ausente_da_erro_amigavel(client, monkeypatch):
    monkeypatch.setattr("forja.orquestracao.area_trabalho.shutil.which", lambda _n: None)
    r = client.get(f"{A}/docker")
    assert r.status_code == 422 and "Docker" in r.text
    assert client.get(f"{A}/docker", params={"recurso": "inspect"}).status_code == 422
    assert client.post(f"{A}/docker", json={"id": "abc", "acao": "exec"}).status_code == 422
    assert client.get(f"{A}/docker/logs", params={"id": "-x; rm"}).status_code == 422


def test_linguagem_de():
    assert linguagem_de("Dockerfile") == "docker" and linguagem_de("a.TSX") == "typescript" and linguagem_de("x.zzz") == "texto"


def test_pasta_sem_git_nao_e_erro_no_status(client, proj):
    pid, _, _ = proj
    r = client.get(f"{A}/git", params={"projeto": pid})
    assert r.status_code == 200 and r.json()["dados"] == {"branch": "", "alterados": [], "repositorio": False}
    assert client.get(f"{A}/git", params={"projeto": pid, "operacao": "log"}).status_code == 422  # as outras operacoes avisam


def test_quadro_usa_rotulos_acentuados(client):
    rotulos = {c["id"]: c["rotulo"] for c in client.get("/api/v1/kanban").json()["colunas"]}
    assert rotulos["executando"] == "Em execução" and rotulos["atencao"] == "Precisa de você" and rotulos["concluida"] == "Concluída"
