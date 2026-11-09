"""API de memoria: autenticacao, ACL por HTTP, validacao, ingestao restrita a raizes, grafo."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.adapters.sqlite import tabelas as T
from forja.config import Configuracoes
from forja.servidor.app import criar_app

TOKEN = "token-de-teste-com-tamanho-suficiente"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BASE = {"tipo": "semantica", "titulo": "SQLite usa WAL", "resumo": "modo de journal", "conteudo": "WAL permite leitores", "namespace": "publico"}


def _cfg(tmp_path: Path, **extra) -> Configuracoes:
    return Configuracoes(_env_file=None, app_data_dir=tmp_path / "data", app_log_dir=tmp_path / "logs",  # type: ignore[call-arg]
                         app_api_token=TOKEN, app_allowed_hosts="testserver", **extra)


@pytest.fixture
def cli(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(criar_app(_cfg(tmp_path), AgenteMock()), headers=AUTH) as c:
        yield c


@pytest.fixture
def cli_ampla(tmp_path: Path) -> Iterator[TestClient]:
    (tmp_path / "repos" / "demo").mkdir(parents=True)
    cfg = _cfg(tmp_path, app_memory_allowed_namespaces="publico,pessoal,empresa/acme",
               app_memory_ingest_roots=str(tmp_path / "repos"))
    with TestClient(criar_app(cfg, AgenteMock()), headers=AUTH) as c:
        yield c


def evidencia_real(c: TestClient) -> str:
    repo = c.app.state.servico.repo
    with repo.escrita() as t:
        t.inserir(T.Projeto, id="PX", nome="px", descricao="", estado="ativo", criado_em="2026")
        t.inserir(T.Objetivo, id="OX", projeto_id="PX", titulo="o", descricao="", prioridade=3, criterios_sucesso=[],
                  orcamento={}, criado_em="2026")
        t.inserir(T.Tarefa, id="TX", objetivo_id="OX", projeto_id="PX", titulo="t", descricao="", criterios_aceite=["x"],
                  dependencias=[], especialidade="g", modo="analise", recursos={}, orcamento={}, politicas={}, entrada={},
                  contexto_refs=[], estado="concluida", versao_estado=1, tentativas=1, motivo_estado="",
                  correlation_id="c", criado_em="2026", atualizado_em="2026")
        t.inserir(T.Evidencia, id="EVX", tarefa_id="TX", execucao_id=None, tipo="teste", resumo="ok", artefato_id=None,
                  simulada=False, criado_em="2026")
    return "EVX"


def test_memoria_exige_autenticacao(cli):
    sem = TestClient(cli.app)
    assert sem.get("/api/v1/memorias/buscar?q=x").status_code == 401
    assert sem.post("/api/v1/memorias", json=BASE).status_code == 401
    assert sem.delete("/api/v1/memorias/MEM-x").status_code == 401
    assert sem.post("/api/v1/memorias/ingerir", json={"namespace": "publico", "raiz": ".", "repositorio": "r"}).status_code == 401


def test_criar_buscar_obter(cli):
    r = cli.post("/api/v1/memorias", json=BASE)
    assert r.status_code == 201 and r.json()["estado"] == "candidato"
    mid = r.json()["id"]
    b = cli.get("/api/v1/memorias/buscar", params={"q": "WAL"}).json()  # namespace padrao: publico
    assert [x["id"] for x in b["resultados"]] == [mid] and b["resultados"][0]["hipotese"] is True
    assert cli.get(f"/api/v1/memorias/{mid}").json()["conteudo_nao_confiavel"] is True


def test_namespace_sem_permissao_e_403_na_busca_e_na_criacao(cli):
    erro = cli.post("/api/v1/memorias", json={**BASE, "namespace": "empresa/acme"})
    assert erro.status_code == 403 and erro.json()["erro"] == "acesso_negado"
    assert cli.get("/api/v1/memorias/buscar", params={"q": "x", "namespace": "empresa/acme"}).status_code == 403
    assert cli.get("/api/v1/memorias/buscar", params={"q": "x", "namespace": ["publico", "terceiros"]}).status_code == 403


def test_memoria_de_outro_namespace_e_404_nao_403(cli_ampla, tmp_path):
    mid = cli_ampla.post("/api/v1/memorias", json={**BASE, "namespace": "empresa/acme"}).json()["id"]
    # reinicia a app SEM acesso a empresa/acme, sobre o mesmo banco
    with TestClient(criar_app(_cfg(tmp_path), AgenteMock()), headers=AUTH) as restrito:
        assert restrito.get(f"/api/v1/memorias/{mid}").status_code == 404
        assert restrito.delete(f"/api/v1/memorias/{mid}").status_code == 404
        achados = restrito.get("/api/v1/memorias/buscar", params={"q": "WAL"}).json()["resultados"]
        assert achados == []


@pytest.mark.parametrize("corpo", [
    {**BASE, "namespace": "qualquer"}, {**BASE, "namespace": "../publico"}, {**BASE, "titulo": ""},
    {**BASE, "tipo": "inventado"}, {**BASE, "extra": 1}, {**BASE, "confianca": 1.5},
    {**BASE, "fonte": {"caminho": "../../etc/passwd"}}, {**BASE, "fonte": {"caminho": "C:/Windows/x"}},
])
def test_entradas_invalidas_sao_422(cli, corpo):
    assert cli.post("/api/v1/memorias", json=corpo).status_code == 422


def test_busca_valida_parametros(cli):
    assert cli.get("/api/v1/memorias/buscar").status_code == 422
    assert cli.get("/api/v1/memorias/buscar", params={"q": "x", "limite": 999}).status_code == 422
    assert cli.get("/api/v1/memorias/buscar", params={"q": "x", "fonte": "banco"}).status_code == 422
    assert cli.get("/api/v1/memorias/buscar", params={"q": "!!!"}).status_code == 422


def test_ciclo_de_promocao_via_api(cli):
    mid = cli.post("/api/v1/memorias", json=BASE).json()["id"]
    assert cli.post(f"/api/v1/memorias/{mid}/transicao", json={"para": "verificado", "expected_version": 1}).status_code == 409
    assert cli.post(f"/api/v1/memorias/{mid}/transicao", json={"para": "validado", "expected_version": 1}).status_code == 409
    assert cli.post(f"/api/v1/memorias/{mid}/evidencias", json={"evidencia_id": "EV-nao-existe"}).status_code == 404
    assert cli.post(f"/api/v1/memorias/{mid}/evidencias", json={"evidencia_id": evidencia_real(cli)}).status_code == 200
    assert cli.post(f"/api/v1/memorias/{mid}/transicao", json={"para": "verificado", "expected_version": 1}).status_code == 200
    assert cli.post(f"/api/v1/memorias/{mid}/validar", json={"expected_version": 1, "validado_por": "x"}).status_code == 409  # versao
    ok = cli.post(f"/api/v1/memorias/{mid}/validar", json={"expected_version": 2, "validado_por": "teste_integracao"})
    assert ok.status_code == 200 and ok.json()["estado"] == "validado"
    so_validadas = cli.get("/api/v1/memorias/buscar", params={"q": "WAL", "apenas_validadas": True}).json()
    assert so_validadas["resultados"][0]["hipotese"] is False


def test_patch_e_delete(cli):
    mid = cli.post("/api/v1/memorias", json=BASE).json()["id"]
    p = cli.patch(f"/api/v1/memorias/{mid}", json={"expected_version": 1, "titulo": "WAL e journal"})
    assert p.status_code == 200 and p.json()["versao"] == 2
    assert cli.patch(f"/api/v1/memorias/{mid}", json={"expected_version": 1, "titulo": "x"}).status_code == 409
    assert cli.delete(f"/api/v1/memorias/{mid}").status_code == 204
    assert cli.get(f"/api/v1/memorias/{mid}").status_code == 404


def test_ingestao_desligada_por_padrao(cli, tmp_path):
    r = cli.post("/api/v1/memorias/ingerir", json={"namespace": "publico", "raiz": str(tmp_path), "repositorio": "r"})
    assert r.status_code == 403 and "desabilitada" in r.json()["mensagem"]


def test_ingestao_so_dentro_das_raizes_e_busca_codigo(cli_ampla, tmp_path):
    raiz = tmp_path / "repos" / "demo"
    (raiz / "svc.py").write_text("class ServicoDemo:\n    def rodar(self):\n        return 1\n", encoding="utf-8")
    ok = cli_ampla.post("/api/v1/memorias/ingerir", json={"namespace": "publico", "raiz": str(raiz), "repositorio": "demo"})
    assert ok.status_code == 200 and ok.json()["novos"] == 1
    fora = cli_ampla.post("/api/v1/memorias/ingerir", json={"namespace": "publico", "raiz": str(tmp_path), "repositorio": "r"})
    assert fora.status_code == 403
    achados = cli_ampla.get("/api/v1/memorias/buscar", params={"q": "ServicoDemo", "fonte": "codigo"}).json()["resultados"]
    assert achados[0]["caminho"] == "svc.py" and achados[0]["origem"] == "codigo"
    assert cli_ampla.get("/api/v1/memorias/estatisticas").json()["arquivos_indexados"] == 1


def test_grafo_via_api(cli):
    a = cli.post("/api/v1/conhecimento/nos", json={"tipo": "Erro", "nome": "E1", "namespace": "publico"}).json()
    b = cli.post("/api/v1/conhecimento/nos", json={"tipo": "Solucao", "nome": "S1", "namespace": "publico"}).json()
    assert cli.post("/api/v1/conhecimento/nos", json={"tipo": "Foguete", "nome": "x", "namespace": "publico"}).status_code == 422
    ar = cli.post("/api/v1/conhecimento/arestas", json={"origem": b["id"], "destino": a["id"], "tipo": "CORRIGE", "namespace": "publico"})
    assert ar.status_code == 201
    v = cli.get(f"/api/v1/conhecimento/nos/{a['id']}/vizinhos").json()
    assert {n["nome"] for n in v["nos"]} == {"E1", "S1"} and len(v["arestas"]) == 1
    assert cli.get(f"/api/v1/conhecimento/nos/{a['id']}/vizinhos", params={"saltos": 5}).status_code == 422


def test_eventos_de_memoria_chegam_ao_sse_sem_conteudo(cli):
    cli.post("/api/v1/memorias", json={**BASE, "titulo": "TITULO-SECRETO-QQQ", "conteudo": "CONTEUDO-SECRETO-QQQ"})
    with cli.stream("GET", "/api/v1/eventos/stream?after_id=0&follow=false") as resp:
        corpo = "".join(resp.iter_text())
    assert "memoria.criada" in corpo and "SECRETO" not in corpo
