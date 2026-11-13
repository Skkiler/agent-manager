"""Master e sub-masters (agente simulado): conversa -> tarefas, sub-master so com 2+ projetos, limites, consolidacao e rotas."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.config import Configuracoes
from forja.orquestracao.coordenacao import MAX_ACOES, extrair
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


def esperar(fn, tentativas: int = 200):
    for _ in range(tentativas):
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("condicao nao atingida")


def test_extrair_e_tolerante():
    r, a, av = extrair("## Resposta\nOk.\n## Ações\n```json\n{\"acoes\": [{\"tipo\": \"criar_tarefa\"}, 3]}\n```")
    assert r == "Ok." and a == [{"tipo": "criar_tarefa"}] and av == []
    r, a, av = extrair("## Resposta\nOi\n```json\n{quebrado}\n```")
    assert a == [] and av and r == "Oi"
    assert extrair("so texto") == ("so texto", [], [])


def test_master_cria_tarefa_que_executa_e_consolida(cli):
    r = cli.post("/api/v1/master/conversa", json={"texto": "Revise o projeto alfa, por favor"})
    assert r.status_code == 200 and r.json()["tarefa_id"]

    def consolidado():
        p = cli.get("/api/v1/master").json()
        papeis = [m["papel"] for m in p["conversa"]]
        return p if papeis.count("master") >= 2 else None

    p = esperar(consolidado)
    tarefas = p["master"]["tarefas"]
    assert len(tarefas) == 1 and tarefas[0]["estado"] == "concluida" and tarefas[0]["modo"] == "analise"
    conversa = p["conversa"]
    assert conversa[0]["papel"] == "usuario"
    assert any(m["papel"] == "sistema" and "Concluída" in m["conteudo"] for m in conversa)  # retorno da tarefa
    assert "Lote concluído" in [m for m in conversa if m["papel"] == "master"][-1]["conteudo"]
    projetos = {x["nome"] for x in cli.get("/api/v1/projetos").json()}
    assert "alfa" in projetos
    # turnos internos nao poluem o quadro; a tarefa de trabalho aparece
    kanban = cli.get("/api/v1/kanban").json()
    titulos = [c["titulo"] for col in kanban["colunas"] for c in col["cartoes"]]
    assert titulos == [tarefas[0]["titulo"]]


def test_dois_projetos_viram_submasters_que_reportam(cli):
    cli.post("/api/v1/master/conversa", json={"texto": "Documente os projetos beta e gama"})

    def pronto():
        p = cli.get("/api/v1/master").json()
        subs = p["submasters"]
        ok = len(subs) == 2 and all(s["tarefas"] and s["tarefas"][0]["estado"] == "concluida" for s in subs)
        relatos = [m for m in p["conversa"] if m["papel"] == "submaster"]
        return p if ok and len(relatos) >= 4 and [m for m in p["conversa"] if m["papel"] == "master"][-1:] and \
            any("Lote concluído" in m["conteudo"] for m in p["conversa"] if m["papel"] == "master") else None

    p = esperar(pronto, 400)
    assert {s["titulo"] for s in p["submasters"]} == {"Sub-master beta", "Sub-master gama"}
    assert all(s["tipo"] == "submaster" and s["max_chamadas"] == 15 for s in p["submasters"])
    sub = cli.get(f"/api/v1/coordenacoes/{p['submasters'][0]['id']}").json()
    assert sub["conversa"][0]["papel"] == "master"  # o master passou o objetivo


def test_um_projeto_so_nao_cria_submaster(cli):
    svc = cli.app.state.coordenacao
    m = svc.master()
    criadas, recusadas = svc._aplicar(m, [{"tipo": "criar_submaster", "projeto": "delta", "objetivo": "refatorar o modulo x"}])
    assert [c["tipo"] for c in criadas] == ["tarefa"] and not recusadas


def test_limites_e_modos(cli):
    svc = cli.app.state.coordenacao
    svc.executar = False
    m = svc.master()
    brutas = [{"tipo": "criar_tarefa", "projeto": "eps", "titulo": f"tarefa {i}", "modo": "analise"} for i in range(MAX_ACOES + 3)]
    criadas, _ = svc._aplicar(m, brutas)
    assert len(criadas) == MAX_ACOES  # o excedente e ignorado
    _, recusadas = svc._aplicar(m, [{"tipo": "criar_tarefa", "projeto": "eps", "titulo": "mudar codigo", "modo": "alteracao_codigo"}])
    assert recusadas and "nao permitido" in recusadas[0]  # autonomia padrao nao permite alterar codigo
    _, recusadas = svc._aplicar(m, [{"tipo": "criar_tarefa", "projeto": "forja-coordenacao", "titulo": "reservado"}])
    assert recusadas and "reservado" in recusadas[0]
    _, recusadas = svc._aplicar(m, [{"tipo": "criar_tarefa", "projeto": "eps", "titulo": "x"}])  # titulo curto demais
    assert recusadas and "formato" in recusadas[0]


def test_submaster_nao_cria_submaster_e_fica_no_proprio_projeto(cli):
    svc = cli.app.state.coordenacao
    svc.executar = False
    m = svc.master()
    criadas, _ = svc._aplicar(m, [{"tipo": "criar_submaster", "projeto": "p1", "objetivo": "objetivo um"},
                                  {"tipo": "criar_submaster", "projeto": "p2", "objetivo": "objetivo dois"}])
    sub = svc.obter(criadas[0]["id"])
    criadas2, recusadas = svc._aplicar(sub, [{"tipo": "criar_submaster", "projeto": "p3", "objetivo": "neto"},
                                             {"tipo": "criar_tarefa", "projeto": "outro", "titulo": "tarefa do sub"}])
    assert "profundidade" in recusadas[0]
    t = cli.get(f"/api/v1/tarefas/{criadas2[0]['id']}").json()
    proj = {p["id"]: p["nome"] for p in cli.get("/api/v1/projetos").json()}
    assert proj[t["projeto_id"]] == "p1"


def test_orcamento_esgotado_e_encerrado(cli):
    svc = cli.app.state.coordenacao
    m = svc.master()
    with svc.servico.repo.escrita() as t:
        from forja.adapters.sqlite import tabelas as T

        t.atualizar(T.Coordenacao, m["id"], chamadas_usadas=m["max_chamadas"])
    r = cli.post("/api/v1/master/conversa", json={"texto": "mais um pedido"}).json()
    assert r["recusado"] == "orcamento"
    assert cli.post(f"/api/v1/coordenacoes/{m['id']}/encerrar").json()["estado"] == "encerrado"
    novo = cli.get("/api/v1/master").json()["master"]
    assert novo["id"] != m["id"]  # um master novo e aberto
    r = cli.post("/api/v1/master/conversa", json={"texto": "x", "coordenacao_id": m["id"]})
    assert r.status_code == 409


def test_rotas_validam(cli):
    assert cli.post("/api/v1/master/conversa", json={"texto": ""}).status_code == 422
    assert cli.post("/api/v1/master/conversa", json={"texto": "ok", "extra": 1}).status_code == 422
    assert cli.get("/api/v1/coordenacoes/NAO-EXISTE").status_code == 404
    assert cli.get("/api/v1/provedores").json()["agentes"][0]["simulado"] is True
    assert TestClient(cli.app).get("/api/v1/master").status_code == 401  # sem credencial


def test_rotas_do_caderno_e_do_status(cli):
    from tests.test_conversa_api import esperar as esperar_estado
    from tests.test_conversa_api import tarefa_pronta

    t = tarefa_pronta(cli, "ok")
    r = cli.post(f"/api/v1/tarefas/{t['id']}/caderno", json={"tipo": "resolvido", "texto": "import corrigido", "ref": "src/a.py"})
    assert r.status_code == 200 and r.json()["origem"] == "agente"
    assert cli.post(f"/api/v1/tarefas/{t['id']}/caderno", json={"tipo": "x", "texto": "y"}).status_code == 422
    assert cli.post(f"/api/v1/tarefas/{t['id']}/caderno", json={"tipo": "fato", "texto": "y" * 601}).status_code == 422
    assert cli.post("/api/v1/tarefas/T-nada/caderno", json={"tipo": "fato", "texto": "y"}).status_code == 404
    assert [i["texto"] for i in cli.get(f"/api/v1/tarefas/{t['id']}/caderno", params={"q": "IMPORT"}).json()] == ["import corrigido"]
    assert cli.get("/api/v1/tarefas/T-nada/caderno").status_code == 404
    ex = cli.post(f"/api/v1/tarefas/{t['id']}/execucoes").json()
    cli.post(f"/api/v1/execucoes/{ex['id']}/iniciar")
    esperar_estado(cli, t["id"], "concluida")
    st = cli.get(f"/api/v1/execucoes/{ex['id']}/status").json()
    assert st["tarefa_id"] == t["id"] and st["estado"] == "concluida" and isinstance(st["linha"], list)
    assert cli.get("/api/v1/execucoes/EX-nada/status").status_code == 404
