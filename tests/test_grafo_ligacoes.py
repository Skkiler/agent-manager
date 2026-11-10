"""4.22: ligacoes tipadas criadas/removidas pela tela do grafo, com ontologia e ACL."""

from __future__ import annotations

import pytest

from forja.dominio.erros import Conflito, NaoEncontrado, ValidacaoDominio
from forja.memoria.contratos import MemoriaIn
from forja.memoria.modelo import Principal
from forja.orquestracao.grafo_servico import GrafoServico
from forja.orquestracao.memoria_servico import ServicoMemoria

TODOS = Principal("op", frozenset({"publico", "pessoal"}))
SO_PUBLICO = Principal("outro", frozenset({"publico"}))


@pytest.fixture
def notas(repo):
    s = ServicoMemoria(repo)
    mk = lambda titulo, ns="publico": s.criar(TODOS, MemoriaIn(tipo="semantica", titulo=titulo, resumo=titulo, conteudo=titulo, tags=[], namespace=ns))["id"]  # noqa: E731
    return GrafoServico(repo), mk("Fila"), mk("Heapq"), mk("Diario", "pessoal")


def test_ligar_aparece_no_grafo_como_editavel_e_remover_some(notas):
    g, a, b, _ = notas
    lg = g.ligar(TODOS, a, b, "DEPENDE_DE", "usa heap")
    arestas = g.grafo(TODOS, ["publico"])["arestas"]
    tipada = [x for x in arestas if x.get("editavel")]
    assert tipada == [{"origem": a, "destino": b, "tipo": "DEPENDE_DE", "id": lg["id"], "editavel": True, "nota": "usa heap"}]
    with pytest.raises(Conflito):
        g.ligar(TODOS, a, b, "DEPENDE_DE")
    g.desligar(TODOS, lg["id"])
    assert not [x for x in g.grafo(TODOS, ["publico"])["arestas"] if x.get("editavel")]
    with pytest.raises(NaoEncontrado):
        g.desligar(TODOS, lg["id"])


def test_ontologia_e_laco_sao_validados(notas):
    g, a, b, _ = notas
    with pytest.raises(ValidacaoDominio):
        g.ligar(TODOS, a, b, "GOSTA_DE")
    with pytest.raises(ValidacaoDominio):
        g.ligar(TODOS, a, a, "DEPENDE_DE")


def test_acl_sem_oraculo_e_ligacao_privada_fica_no_escopo_privado(notas):
    g, a, _b, privada = notas
    with pytest.raises(NaoEncontrado):
        g.ligar(SO_PUBLICO, a, privada, "BASEADO_EM")  # quem nao ve 'pessoal' nao sabe se existe
    lg = g.ligar(TODOS, a, privada, "BASEADO_EM")
    assert lg["namespace"] == "pessoal"
    assert not [x for x in g.grafo(SO_PUBLICO, ["publico"])["arestas"] if x.get("editavel")]
    with pytest.raises(NaoEncontrado):
        g.desligar(SO_PUBLICO, lg["id"])


def test_api(client):
    assert "DEPENDE_DE" in client.get("/api/v1/conhecimento/tipos-de-ligacao").json()
    c = lambda t: client.post("/api/v1/memorias", json={"tipo": "semantica", "titulo": t, "conteudo": t, "namespace": "publico"}).json()["id"]  # noqa: E731
    a, b = c("A1"), c("B1")
    r = client.post("/api/v1/conhecimento/ligacoes", json={"origem": a, "destino": b, "tipo": "IMPLEMENTA"})
    assert r.status_code == 201
    assert client.post("/api/v1/conhecimento/ligacoes", json={"origem": a, "destino": b, "tipo": "IMPLEMENTA"}).status_code == 409
    assert client.post("/api/v1/conhecimento/ligacoes", json={"origem": a, "destino": "NAO", "tipo": "IMPLEMENTA"}).status_code == 404
    assert client.delete(f"/api/v1/conhecimento/ligacoes/{r.json()['id']}").status_code == 204
