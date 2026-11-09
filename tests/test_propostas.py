"""Segundo cerebro: proposta de memoria candidata a partir de tarefa concluida (item 3.10)."""

from __future__ import annotations

import shutil
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.config import Configuracoes
from forja.servidor.app import criar_app

TOKEN = "token-de-teste-com-tamanho-suficiente"


@pytest.fixture
def cli(tmp_path: Path, _db_migrado: Path) -> Iterator[TestClient]:
    (tmp_path / "data").mkdir()
    shutil.copyfile(_db_migrado, tmp_path / "data" / "forja.sqlite3")
    cfg = Configuracoes(_env_file=None, app_data_dir=tmp_path / "data", app_log_dir=tmp_path / "logs",  # type: ignore[call-arg]
                        app_api_token=TOKEN, app_allowed_hosts="testserver")
    with TestClient(criar_app(cfg, AgenteMock()), headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c


def _tarefa(c: TestClient, preparar: bool = True) -> dict:
    p = c.post("/api/v1/projetos", json={"nome": f"p-{time.time_ns()}"}).json()
    o = c.post("/api/v1/objetivos", json={"projeto_id": p["id"], "titulo": "o"}).json()
    t = c.post("/api/v1/tarefas", json={"objetivo_id": o["id"], "titulo": "Configurar autenticacao Bearer",
                                        "descricao": "Definir como a API autentica clientes.",
                                        "criterios_aceite": ["token validado", "erros claros"],
                                        "entrada": {"mock_passos": 1}}).json()
    if preparar:
        k = c.post(f"/api/v1/tarefas/{t['id']}/transicao", json={"para": "classificada", "expected_version": 1}).json()
        c.post(f"/api/v1/tarefas/{t['id']}/transicao", json={"para": "preparada", "expected_version": k["versao_estado"]})
    return c.get(f"/api/v1/tarefas/{t['id']}").json()


def _concluir(c: TestClient) -> dict:
    t = _tarefa(c)
    ex = c.post(f"/api/v1/tarefas/{t['id']}/execucoes").json()
    c.post(f"/api/v1/execucoes/{ex['id']}/iniciar")
    for _ in range(200):
        atual = c.get(f"/api/v1/tarefas/{t['id']}").json()
        if atual["estado"] == "concluida":
            return atual
        time.sleep(0.05)
    raise AssertionError(f"nao concluiu: {atual['estado']}")


def test_proposta_cria_memoria_candidata_com_fonte_e_referencias(cli):
    t = _concluir(cli)
    r = cli.post(f"/api/v1/tarefas/{t['id']}/propor-memoria", json={"namespace": "pessoal"})
    assert r.status_code == 201
    corpo = r.json()
    m = corpo["memoria"]
    assert corpo["criada"] and m["estado"] == "candidato"  # nunca nasce validada
    assert m["titulo"].startswith("Procedimento: Configurar autenticacao")
    assert f"tarefa:{t['id']}" in m["refs"] and m["fonte"]["tipo"] == "execucao"
    assert "token validado" in m["conteudo"] and "## Evidencias" in m["conteudo"]
    assert "proposta" in m["tags"]
    # o mock produz evidencia SIMULADA: ela e rotulada, nao e vinculada e o aviso e explicito
    assert "(SIMULADA)" in m["conteudo"]
    assert any("simulada" in a for a in corpo["avisos"]) and any("sem evidencia real" in a for a in corpo["avisos"])


def test_proposta_e_idempotente_e_a_memoria_e_encontravel(cli):
    t = _concluir(cli)
    a = cli.post(f"/api/v1/tarefas/{t['id']}/propor-memoria", json={"namespace": "pessoal"})
    b = cli.post(f"/api/v1/tarefas/{t['id']}/propor-memoria", json={"namespace": "pessoal"})
    assert (a.status_code, b.status_code) == (201, 200) and a.json()["memoria"]["id"] == b.json()["memoria"]["id"]
    achados = cli.get("/api/v1/memorias/buscar", params={"q": "autenticacao Bearer", "namespace": "pessoal",
                                                         "fonte": "memoria"}).json()["resultados"]
    assert any(x.get("id") == a.json()["memoria"]["id"] for x in achados)


def test_proposta_nao_validada_automaticamente_e_nao_vira_contexto_do_prompt(cli):
    t = _concluir(cli)
    m = cli.post(f"/api/v1/tarefas/{t['id']}/propor-memoria", json={"namespace": "pessoal"}).json()["memoria"]
    validar = cli.post(f"/api/v1/memorias/{m['id']}/validar", json={"expected_version": m["versao"], "validado_por": "x"})
    assert validar.status_code in (409, 422)  # candidato nao pula etapas: exige verificado com evidencia real


def test_proposta_recusa_tarefa_nao_concluida_inexistente_e_namespace_sem_acesso(cli):
    nao_concluida = _tarefa(cli, preparar=False)
    assert cli.post(f"/api/v1/tarefas/{nao_concluida['id']}/propor-memoria", json={"namespace": "pessoal"}).status_code == 409
    assert cli.post("/api/v1/tarefas/T-nao-existe/propor-memoria", json={"namespace": "pessoal"}).status_code == 404
    t = _concluir(cli)
    assert cli.post(f"/api/v1/tarefas/{t['id']}/propor-memoria", json={"namespace": "empresa/acme"}).status_code == 403
    assert cli.post(f"/api/v1/tarefas/{t['id']}/propor-memoria", json={"namespace": "invalido!"}).status_code == 422
    assert cli.post(f"/api/v1/tarefas/{t['id']}/propor-memoria", json={}).status_code == 422
