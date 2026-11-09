"""Visoes da interface: Kanban de tarefas e grafo do segundo cerebro (wikilinks, backlinks, ACL)."""

from __future__ import annotations

import shutil
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.adapters.sqlite import tabelas as T
from forja.config import Configuracoes
from forja.dominio.estados import TRANSICOES, EstadoTarefa, eh_terminal
from forja.orquestracao.visoes import COLUNAS, VisaoKanban, acoes_do_cartao
from forja.servidor.app import criar_app

TOKEN = "token-de-teste-com-tamanho-suficiente"

# ---------------------------------------------------------------- Kanban


def test_todo_estado_pertence_a_exatamente_uma_coluna():
    todos = [e for _, _, estados in COLUNAS for e in estados]
    assert sorted(e.value for e in todos) == sorted(e.value for e in EstadoTarefa)  # nenhum faltando nem repetido


@pytest.mark.parametrize("estado", [e.value for e in EstadoTarefa])
def test_acoes_do_cartao_por_estado(estado: str):
    ids = [a["id"] for a in acoes_do_cartao(estado)]
    assert ("cancelar" in ids) is (not eh_terminal(EstadoTarefa(estado)))  # terminal nao cancela
    assert ids.count("conversa") <= 1
    assert ("executar" in ids) is (estado == "pronta")
    assert ("preparar" in ids) is (estado in ("rascunho", "classificada"))
    if estado == "bloqueada":
        assert acoes_do_cartao(estado)[0] == {"id": "conversa", "rotulo": "Responder"}


def test_acoes_oferecidas_sempre_correspondem_a_transicoes_validas():
    for e in EstadoTarefa:
        if any(a["id"] == "cancelar" for a in acoes_do_cartao(e.value)):
            assert EstadoTarefa.CANCELADA in TRANSICOES[e], e


def _tarefa(repo, n: int, estado: str, prioridade: int = 3, atualizado: str = "2026-01-01T00:00:00") -> str:
    with repo.escrita() as t:
        if t.obter(T.Projeto, "P1") is None:
            t.inserir(T.Projeto, id="P1", nome="p1", descricao="", estado="ativo", criado_em="2026")
        t.inserir(T.Objetivo, id=f"O{n}", projeto_id="P1", titulo="o", descricao="", prioridade=prioridade,
                  criterios_sucesso=[], orcamento={}, criado_em="2026")
        t.inserir(T.Tarefa, id=f"T{n}", objetivo_id=f"O{n}", projeto_id="P1", titulo=f"tarefa {n}", descricao="",
                  criterios_aceite=["x"], dependencias=["T0"] if n == 9 else [], especialidade="g", modo="analise",
                  recursos={}, orcamento={}, politicas={}, entrada={}, contexto_refs=[], estado=estado,
                  versao_estado=1, tentativas=2, motivo_estado="m" * 300, correlation_id="c", criado_em="2026",
                  atualizado_em=atualizado)
    return f"T{n}"


def test_kanban_agrupa_por_coluna_ordena_por_prioridade_e_conta_o_que_precisa_de_voce(repo, relogio):
    _tarefa(repo, 1, "rascunho", prioridade=5)
    _tarefa(repo, 2, "preparada", prioridade=1)
    _tarefa(repo, 3, "bloqueada")
    _tarefa(repo, 4, "aguardando_aprovacao")
    _tarefa(repo, 5, "concluida")
    _tarefa(repo, 6, "cancelada")
    _tarefa(repo, 9, "rascunho", prioridade=1, atualizado="2026-06-01T00:00:00")
    k = VisaoKanban(repo, relogio).montar()
    cols = {c["id"]: c for c in k["colunas"]}
    assert k["total"] == 7 and k["precisa_de_voce"] == 2
    assert [c["id"] for c in cols["backlog"]["cartoes"]] == ["T9", "T2", "T1"]  # prioridade 1 (mais recente 1o), depois 5
    assert {c["id"] for c in cols["atencao"]["cartoes"]} == {"T3", "T4"}
    assert all(c["precisa_de_voce"] for c in cols["atencao"]["cartoes"])
    card = cols["backlog"]["cartoes"][0]
    assert card["dependencias"] == 1 and len(card["motivo"]) == 160 and card["tentativas"] == 2
    assert cols["encerradas"]["total"] == 1 and cols["concluida"]["cartoes"][0]["acoes"][0]["id"] == "conversa"


def test_kanban_limita_cartoes_por_coluna_mas_informa_o_total(repo, relogio):
    for n in range(1, 56):
        _tarefa(repo, n, "concluida")
    col = next(c for c in VisaoKanban(repo, relogio).montar()["colunas"] if c["id"] == "concluida")
    assert col["total"] == 55 and len(col["cartoes"]) == 50


@pytest.fixture
def cli(tmp_path: Path, _db_migrado: Path) -> Iterator[TestClient]:
    (tmp_path / "data").mkdir()
    shutil.copyfile(_db_migrado, tmp_path / "data" / "forja.sqlite3")
    cfg = Configuracoes(_env_file=None, app_data_dir=tmp_path / "data", app_log_dir=tmp_path / "logs",  # type: ignore[call-arg]
                        app_api_token=TOKEN, app_allowed_hosts="testserver")
    with TestClient(criar_app(cfg, AgenteMock()), headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c


def test_api_kanban_filtra_por_projeto_e_reflete_a_preparacao(cli: TestClient):
    def nova(nome: str) -> dict:
        p = cli.post("/api/v1/projetos", json={"nome": f"{nome}-{time.time_ns()}"}).json()
        o = cli.post("/api/v1/objetivos", json={"projeto_id": p["id"], "titulo": "o"}).json()
        t = cli.post("/api/v1/tarefas", json={"objetivo_id": o["id"], "titulo": nome, "criterios_aceite": ["x"]}).json()
        return {"p": p, "t": t}

    a, b = nova("a"), nova("b")
    todos = cli.get("/api/v1/kanban").json()
    assert todos["total"] == 2
    so_a = cli.get("/api/v1/kanban", params={"projeto_id": a["p"]["id"]}).json()
    cartoes = [c for col in so_a["colunas"] for c in col["cartoes"]]
    assert [c["id"] for c in cartoes] == [a["t"]["id"]] and cartoes[0]["estado"] == "rascunho"
    assert b["t"]["id"] not in str(so_a)
    assert cli.get("/api/v1/kanban", params={"projeto_id": "../x"}).status_code == 422
    sem = TestClient(cli.app, headers={"Host": "testserver"})
    assert sem.get("/api/v1/kanban").status_code in (401, 403)


# ---------------------------------------------------------------- Grafo


def mem(cli: TestClient, titulo: str, conteudo: str = "", ns: str = "publico", tags: list[str] | None = None) -> dict:
    r = cli.post("/api/v1/memorias", json={"tipo": "procedimental", "titulo": titulo, "conteudo": conteudo,
                                           "namespace": ns, "tags": tags or []})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def notas(cli: TestClient) -> dict[str, dict]:
    return {
        "A": mem(cli, "Autenticacao Bearer", "Veja [[Tokens JWT]] e [[Nota Inexistente]]."),
        "B": mem(cli, "Tokens JWT", "Volta para [[autenticacao bearer|a nota A]].", tags=["seguranca"]),
        "C": mem(cli, "Isolada", "Nada aqui."),
    }


def grafo(cli: TestClient, **params) -> dict:
    r = cli.get("/api/v1/conhecimento/grafo", params={"namespace": "publico", **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_grafo_tem_wikilinks_nos_fantasma_e_grau(cli, notas):
    g = grafo(cli)
    por = {n["rotulo"]: n for n in g["nos"]}
    assert {"Autenticacao Bearer", "Tokens JWT", "Isolada", "Nota Inexistente"} <= set(por)
    assert por["Nota Inexistente"]["grupo"] == "fantasma" and por["Autenticacao Bearer"]["grupo"] == "memoria"
    ids = {k: notas[k]["id"] for k in notas}
    pares = {(a["origem"], a["destino"], a["tipo"]) for a in g["arestas"]}
    assert (ids["A"], ids["B"], "wikilink") in pares and (ids["B"], ids["A"], "wikilink") in pares  # ida e volta
    assert (ids["A"], "?Nota Inexistente", "wikilink") in pares
    assert por["Isolada"]["grau"] == 0 and por["Autenticacao Bearer"]["grau"] == 3
    assert g["fantasmas"] == 1 and not g["truncado"]


def test_grafo_busca_traz_sementes_e_vizinhos(cli, notas):
    # so B tem a tag: semente = B; com 1 salto entra o vizinho A; "Isolada" e o fantasma de A ficam fora
    assert {n["rotulo"] for n in grafo(cli, q="seguranca")["nos"]} == {"Tokens JWT", "Autenticacao Bearer"}
    assert {n["rotulo"] for n in grafo(cli, q="seguranca", vizinhos=0)["nos"]} == {"Tokens JWT"}
    # "jwt" aparece no titulo de B e no conteudo de A: ambos sao sementes; o fantasma de A entra como vizinho
    assert {n["rotulo"] for n in grafo(cli, q="jwt", vizinhos=0)["nos"]} == {"Tokens JWT", "Autenticacao Bearer"}
    assert {n["rotulo"] for n in grafo(cli, q="JWT")["nos"]} == {"Tokens JWT", "Autenticacao Bearer", "Nota Inexistente"}
    assert grafo(cli, q="nada-parecido")["nos"] == []


def test_busca_com_varios_termos_exige_todos_eles(cli, notas):
    assert {n["rotulo"] for n in grafo(cli, q="tokens jwt", vizinhos=0)["nos"]} == {"Tokens JWT", "Autenticacao Bearer"}
    assert grafo(cli, q="jwt isolada")["nos"] == []  # "isolada" so existe em C e "jwt" so em A/B: nenhuma nota tem os dois


def test_grafo_respeita_limite_e_mantem_so_arestas_internas(cli, notas):
    g = grafo(cli, limite=2)
    assert len(g["nos"]) == 2 and g["truncado"]
    ids = {n["id"] for n in g["nos"]}
    assert all(a["origem"] in ids and a["destino"] in ids for a in g["arestas"])


def test_grafo_respeita_acl_de_namespace(cli, notas):
    assert cli.get("/api/v1/conhecimento/grafo", params={"namespace": "empresa/acme"}).status_code == 403
    mem(cli, "Segredo pessoal", "[[Autenticacao Bearer]]", ns="pessoal")
    publico = {n["rotulo"] for n in grafo(cli)["nos"]}
    assert "Segredo pessoal" not in publico  # outro namespace nunca aparece nem liga
    ambos = grafo(cli, namespace=["publico", "pessoal"])
    assert "Segredo pessoal" in {n["rotulo"] for n in ambos["nos"]}


def test_grafo_exclui_memorias_revogadas_a_menos_que_pedido(cli, notas):
    c = notas["C"]
    r = cli.post(f"/api/v1/memorias/{c['id']}/transicao", json={"para": "revogado", "expected_version": c["versao"]})
    assert r.status_code == 200, r.text
    assert "Isolada" not in {n["rotulo"] for n in grafo(cli)["nos"]}
    assert "Isolada" in {n["rotulo"] for n in grafo(cli, incluir_inativas=True)["nos"]}


def test_links_mostra_saida_resolvida_ou_nao_e_backlinks(cli, notas):
    a = cli.get(f"/api/v1/memorias/{notas['A']['id']}/links").json()
    assert {(x["titulo"], x["resolvido"]) for x in a["saida"]} == {("Tokens JWT", True), ("Nota Inexistente", False)}
    assert [x["titulo"] for x in a["entrada"]] == ["Tokens JWT"]
    b = cli.get(f"/api/v1/memorias/{notas['B']['id']}/links").json()
    assert [x["titulo"] for x in b["entrada"]] == ["Autenticacao Bearer"]
    assert cli.get("/api/v1/memorias/MEM-nao-existe/links").status_code == 404


def test_links_de_outro_namespace_e_404_sem_revelar_existencia(cli, notas):
    privada = mem(cli, "Privada", ns="pessoal")
    # a instancia permite 'pessoal'; um namespace fora da ACL nao pode ser descoberto por esta rota
    from forja.memoria.modelo import Principal
    from forja.orquestracao.grafo_servico import GrafoServico

    g = GrafoServico(cli.app.state.servico.repo)
    with pytest.raises(Exception, match="nao encontrada"):
        g.links(Principal("so-publico", frozenset({"publico"})), privada["id"])
