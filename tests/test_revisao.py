"""Revisao do esquema: o operador pede que um agente reavalie a plataforma (melhorias x ponto agradavel)."""

from __future__ import annotations

import shutil
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.config import Configuracoes
from forja.orquestracao.revisao import CRITERIOS, ESCOPOS, MAX_SNAPSHOT
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


def test_solicitar_cria_tarefa_de_analise_preparada_sem_executar(cli: TestClient):
    r = cli.post("/api/v1/revisoes", json={"escopo": ["arquitetura", "custo_e_modelos"]})
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    corpo = r.json()
    t = cli.get(f"/api/v1/tarefas/{corpo['tarefa']['id']}").json()
    assert corpo["execucao_id"] is None  # executar consome creditos: so com pedido explicito
    assert t["estado"] in ("preparada", "pronta") and t["modo"] == "analise" and t["criterios_aceite"] == CRITERIOS
    assert t["entrada"] == {"revisao": True, "escopo": ["arquitetura", "custo_e_modelos"], "pesquisar_web": False}
    assert "Nao pesquise na web" in t["descricao"] and "arquitetura, custo_e_modelos" in t["descricao"]
    assert any("Nao altera arquivos" in c for c in t["criterios_aceite"])


def test_snapshot_traz_fatos_medidos_e_cabe_na_descricao(cli: TestClient):
    cli.put("/api/v1/configuracao", json={"expected_version": 0, "configuracao": {"partes": {"revisao": {"modelo": "m-profundo"}}}})
    cli.post("/api/v1/ferramentas/tokens.orcar/executar", json={"entrada": {"itens": [], "orcamento": 10}})
    p = cli.post("/api/v1/projetos", json={"nome": f"p-{time.time_ns()}"}).json()
    o = cli.post("/api/v1/objetivos", json={"projeto_id": p["id"], "titulo": "o"}).json()
    cli.post("/api/v1/tarefas", json={"objetivo_id": o["id"], "titulo": "t", "criterios_aceite": ["x"]})
    snap = cli.post("/api/v1/revisoes", json={"pesquisar_web": True}).json()["snapshot"]
    assert snap["modelos"]["revisao"] == "m-profundo" and snap["modelos"]["execucao"] == "claude-sonnet-5.5"  # padrao da Forja
    assert snap["ferramentas"]["com_uso"]["tokens.orcar"]["chamadas"] == 1
    assert "codigo.outline" in snap["ferramentas"]["sem_uso"] and snap["ferramentas"]["total"] >= 13
    assert set(snap["bibliotecas"]) == {"fastapi", "pydantic", "sqlalchemy", "alembic", "uvicorn"}
    assert snap["tarefas_por_estado"] == {"rascunho": 1} and snap["python"].startswith("3.")
    t = next(x for x in cli.get("/api/v1/tarefas").json() if x["entrada"].get("revisao"))
    assert "CITE fontes" in t["descricao"] and len(t["descricao"]) < MAX_SNAPSHOT + 1500


def test_revisoes_reutilizam_o_mesmo_projeto(cli: TestClient):
    for _ in range(2):
        assert cli.post("/api/v1/revisoes", json={}).status_code == 201
    projetos = [p for p in cli.get("/api/v1/projetos").json() if p["nome"] == "forja-revisoes"]
    assert len(projetos) == 1


def test_executar_inicia_a_execucao_com_o_agente(cli: TestClient):
    r = cli.post("/api/v1/revisoes", json={"executar": True}).json()
    assert r["execucao_id"]
    for _ in range(200):
        t = cli.get(f"/api/v1/tarefas/{r['tarefa']['id']}").json()
        if t["estado"] == "concluida":
            return
        time.sleep(0.05)
    raise AssertionError(f"revisao nao concluiu: {t['estado']}")


@pytest.mark.parametrize("corpo", [{"escopo": []}, {"escopo": ["nada"]}, {"escopo": ["arquitetura"] * 7}, {"x": 1}])
def test_pedido_invalido_e_422(cli: TestClient, corpo: dict):
    assert cli.post("/api/v1/revisoes", json=corpo).status_code == 422


def test_escopos_do_servico_e_do_contrato_coincidem():
    from typing import get_args

    from forja.dominio.revisao import Escopo

    assert set(get_args(Escopo)) == set(ESCOPOS)


def test_exige_autenticacao(cli: TestClient):
    assert TestClient(cli.app, headers={"Host": "testserver"}).post("/api/v1/revisoes", json={}).status_code in (401, 403)
