"""API da conversa e do contexto: fluxo organico por HTTP, autenticacao, validacao."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.config import Configuracoes
from forja.servidor.app import criar_app

TOKEN = "token-de-teste-com-tamanho-suficiente"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def cli(tmp_path: Path, _db_migrado: Path) -> Iterator[TestClient]:
    import shutil

    (tmp_path / "data").mkdir()
    shutil.copyfile(_db_migrado, tmp_path / "data" / "forja.sqlite3")
    cfg = Configuracoes(_env_file=None, app_data_dir=tmp_path / "data", app_log_dir=tmp_path / "logs",  # type: ignore[call-arg]
                        app_api_token=TOKEN, app_allowed_hosts="testserver")
    with TestClient(criar_app(cfg, AgenteMock()), headers=AUTH) as c:
        yield c


def tarefa_pronta(c: TestClient, cenario: str) -> dict:
    p = c.post("/api/v1/projetos", json={"nome": f"p-{time.time_ns()}"}).json()
    o = c.post("/api/v1/objetivos", json={"projeto_id": p["id"], "titulo": "o"}).json()
    t = c.post("/api/v1/tarefas", json={"objetivo_id": o["id"], "titulo": "Definir autenticacao da API",
                                        "criterios_aceite": ["decidir"],
                                        "entrada": {"mock_cenario": cenario, "mock_passos": 1}}).json()
    k = c.post(f"/api/v1/tarefas/{t['id']}/transicao", json={"para": "classificada", "expected_version": 1}).json()
    c.post(f"/api/v1/tarefas/{t['id']}/transicao", json={"para": "preparada", "expected_version": k["versao_estado"]})
    return c.get(f"/api/v1/tarefas/{t['id']}").json()


def esperar(c: TestClient, tarefa_id: str, estado: str, tentativas: int = 150) -> dict:
    t = {}
    for _ in range(tentativas):
        t = c.get(f"/api/v1/tarefas/{tarefa_id}").json()
        if t["estado"] == estado:
            return t
        time.sleep(0.05)
    raise AssertionError(f"tarefa nao chegou a {estado}: {t.get('estado')}")


def test_fluxo_organico_por_http(cli):
    t = tarefa_pronta(cli, "conversa")
    ex = cli.post(f"/api/v1/tarefas/{t['id']}/execucoes").json()
    cli.post(f"/api/v1/execucoes/{ex['id']}/iniciar")
    esperar(cli, t["id"], "bloqueada")
    msgs = cli.get(f"/api/v1/tarefas/{t['id']}/conversa").json()
    assert [m["tipo"] for m in msgs] == ["entendimento", "decisoes"]
    assert len(msgs[1]["dados"]["decisoes"]) == 2
    r = cli.post(f"/api/v1/tarefas/{t['id']}/conversa", json={"conteudo": "Bearer, e sem publicar ainda."})
    assert r.status_code == 200 and r.json()["retomada_execucao_id"] == ex["id"]
    esperar(cli, t["id"], "concluida")
    final = cli.get(f"/api/v1/tarefas/{t['id']}/conversa").json()
    assert [m["papel"] for m in final] == ["agente", "agente", "operador", "agente"]


def test_resposta_sem_retomar(cli):
    t = tarefa_pronta(cli, "conversa")
    ex = cli.post(f"/api/v1/tarefas/{t['id']}/execucoes").json()
    cli.post(f"/api/v1/execucoes/{ex['id']}/iniciar")
    esperar(cli, t["id"], "bloqueada")
    r = cli.post(f"/api/v1/tarefas/{t['id']}/conversa", json={"conteudo": "so uma nota", "retomar": False}).json()
    assert r["retomada_execucao_id"] is None
    assert cli.get(f"/api/v1/tarefas/{t['id']}").json()["estado"] == "bloqueada"


@pytest.mark.parametrize("corpo", [{"conteudo": ""}, {"conteudo": "   "}, {"conteudo": "x" * 8001}, {}, {"conteudo": "a", "extra": 1}])
def test_resposta_invalida_422(cli, corpo):
    t = tarefa_pronta(cli, "sucesso")
    r = cli.post(f"/api/v1/tarefas/{t['id']}/conversa", json=corpo)
    assert r.status_code == 422


def test_tarefa_inexistente_404(cli):
    assert cli.get("/api/v1/tarefas/T-fantasma/conversa").status_code == 404
    assert cli.post("/api/v1/tarefas/T-fantasma/conversa", json={"conteudo": "oi"}).status_code == 404
    assert cli.get("/api/v1/tarefas/T-fantasma/contexto").status_code == 404


def test_endpoints_exigem_autenticacao(cli):
    sem = TestClient(cli.app)
    assert sem.get("/api/v1/tarefas/T-x/conversa").status_code == 401
    assert sem.post("/api/v1/tarefas/T-x/conversa", json={"conteudo": "x"}).status_code == 401
    assert sem.get("/api/v1/tarefas/T-x/contexto").status_code == 401


def test_contexto_da_tarefa_lista_o_que_entrou_no_prompt(cli):
    """O app liga o construtor por padrao; sem memoria relevante o registro existe e custa 0 tokens."""
    t = tarefa_pronta(cli, "sucesso")
    ex = cli.post(f"/api/v1/tarefas/{t['id']}/execucoes").json()
    cli.post(f"/api/v1/execucoes/{ex['id']}/iniciar")
    esperar(cli, t["id"], "concluida")
    uso = cli.get(f"/api/v1/tarefas/{t['id']}/contexto").json()
    assert len(uso) == 1 and all(i["id"].startswith("MEM-BASE-") for i in uso[0]["itens"])  # so a base da Forja, se relevante


def test_politica_de_contexto_validada_na_criacao_da_tarefa(cli):
    p = cli.post("/api/v1/projetos", json={"nome": f"pc-{time.time_ns()}"}).json()
    o = cli.post("/api/v1/objetivos", json={"projeto_id": p["id"], "titulo": "o"}).json()
    base = {"objetivo_id": o["id"], "titulo": "t", "criterios_aceite": ["a"]}
    assert cli.post("/api/v1/tarefas", json={**base, "politicas": {"contexto": "nenhum"}}).status_code == 201
    assert cli.post("/api/v1/tarefas", json={**base, "politicas": {"contexto": "tudo"}}).status_code == 422
    assert cli.post("/api/v1/tarefas", json={**base, "politicas": {"contexto_max_tokens": 5}}).status_code == 422


def test_configuracao_de_contexto_so_libera_namespaces_permitidos(tmp_path):
    with pytest.raises(ValueError, match="subconjunto"):
        Configuracoes(_env_file=None, app_data_dir=tmp_path, app_context_namespaces="empresa/acme")  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="CONTEXT_BUDGET"):
        Configuracoes(_env_file=None, app_data_dir=tmp_path, app_context_budget_tokens=10)  # type: ignore[call-arg]
    ok = Configuracoes(_env_file=None, app_data_dir=tmp_path, app_memory_allowed_namespaces="publico,empresa/acme",  # type: ignore[call-arg]
                       app_context_namespaces="publico,empresa/acme")
    assert ok.contexto_namespaces == ["publico", "empresa/acme"]
