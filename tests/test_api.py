"""Testes da camada HTTP: autenticacao, validacao, idempotencia, SSE, CSRF/host, fluxo via API."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

AUTH = {"Authorization": "Bearer token-de-teste-com-tamanho-suficiente"}


def _criar_tarefa_pronta(client: TestClient, cenario: str = "sucesso") -> dict:
    p = client.post("/api/v1/projetos", json={"nome": f"p-{time.time_ns()}"}).json()
    o = client.post("/api/v1/objetivos", json={"projeto_id": p["id"], "titulo": "o"}).json()
    t = client.post("/api/v1/tarefas", json={"objetivo_id": o["id"], "titulo": "t",
                    "criterios_aceite": ["ok"], "entrada": {"mock_cenario": cenario, "mock_passos": 2}}).json()
    c = client.post(f"/api/v1/tarefas/{t['id']}/transicao",
                    json={"para": "classificada", "expected_version": t["versao_estado"]}).json()
    client.post(f"/api/v1/tarefas/{t['id']}/transicao",
                json={"para": "preparada", "expected_version": c["versao_estado"]})
    return client.get(f"/api/v1/tarefas/{t['id']}").json()


def test_saude_e_publica(client: TestClient):
    semauth = TestClient(client.app)
    assert semauth.get("/api/v1/saude").json()["status"] == "ok"


def test_exige_autenticacao(client: TestClient):
    semauth = TestClient(client.app)
    assert semauth.get("/api/v1/tarefas").status_code == 401
    assert semauth.post("/api/v1/projetos", json={"nome": "x"}).status_code == 401


def test_validacao_payload(client: TestClient):
    r = client.post("/api/v1/projetos", json={"nome": ""})
    assert r.status_code == 422
    r2 = client.post("/api/v1/tarefas", json={"objetivo_id": "OBJ-x", "titulo": "t", "criterios_aceite": []})
    assert r2.status_code == 422  # criterios_aceite exige min_length=1


def test_recurso_com_path_traversal_rejeitado(client: TestClient):
    o = _criar_objetivo(client)
    r = client.post("/api/v1/tarefas", json={"objetivo_id": o, "titulo": "t", "criterios_aceite": ["ok"],
                    "recursos": {"escrita": ["../fora.py"]}})
    assert r.status_code == 422


def _criar_objetivo(client: TestClient) -> str:
    p = client.post("/api/v1/projetos", json={"nome": f"p-{time.time_ns()}"}).json()
    return client.post("/api/v1/objetivos", json={"projeto_id": p["id"], "titulo": "o"}).json()["id"]


def test_idempotencia_header(client: TestClient):
    corpo = {"nome": f"idem-{time.time_ns()}"}
    r1 = client.post("/api/v1/projetos", json=corpo, headers={"Idempotency-Key": "abc"})
    r2 = client.post("/api/v1/projetos", json=corpo, headers={"Idempotency-Key": "abc"})
    assert r1.json()["id"] == r2.json()["id"]
    assert r2.headers.get("Idempotent-Replayed") == "true"


def test_fluxo_execucao_via_api(client: TestClient):
    tarefa = _criar_tarefa_pronta(client, "sucesso")
    ex = client.post(f"/api/v1/tarefas/{tarefa['id']}/execucoes").json()
    assert client.post(f"/api/v1/execucoes/{ex['id']}/iniciar").status_code == 202
    for _ in range(100):
        est = client.get(f"/api/v1/execucoes/{ex['id']}").json()["estado"]
        if est in ("concluida", "falhou"):
            break
        time.sleep(0.05)
    assert est == "concluida"
    final = client.get(f"/api/v1/tarefas/{tarefa['id']}").json()
    assert final["estado"] == "concluida"
    assert final["evidencias"] and final["artefatos"]


def test_objetivo_progresso(client: TestClient):
    tarefa = _criar_tarefa_pronta(client, "sucesso")
    obj = client.get(f"/api/v1/objetivos/{tarefa['objetivo_id']}").json()
    assert obj["total_tarefas"] == 1 and obj["completo"] is False


def test_host_invalido_rejeitado(client: TestClient):
    r = client.get("/api/v1/saude", headers={"host": "evil.example.com"})
    assert r.status_code == 400


def test_origin_cross_site_rejeitada(client: TestClient):
    r = client.post("/api/v1/projetos", json={"nome": "x"},
                    headers={**AUTH, "origin": "http://evil.example.com"})
    assert r.status_code == 403


def test_sse_replay_e_last_event_id(client: TestClient):
    _criar_tarefa_pronta(client, "sucesso")
    eventos = client.get("/api/v1/eventos?after_id=0").json()
    assert any(e["tipo"] == "tarefa.preparada" for e in eventos)
    ult = eventos[-1]["seq"]
    with client.stream("GET", f"/api/v1/eventos/stream?after_id={ult}&follow=false") as resp:
        corpo = "".join(resp.iter_text())
    # stream a partir de 'ult' nao deve reenviar eventos ja vistos (<= ult)
    assert f"id: {ult}\n" not in corpo


def test_stream_exige_token(client: TestClient):
    semauth = TestClient(client.app)
    with semauth.stream("GET", "/api/v1/eventos/stream?follow=false") as resp:
        assert resp.status_code == 401
