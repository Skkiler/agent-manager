"""4.8: rotulagem pelo usuario e medicao da busca sobre o corpus real (aqui, um corpus sintetico pequeno)."""

from __future__ import annotations

import pytest

from forja.adapters.sqlite import tabelas as T
from forja.dominio.erros import ConflitoVersao, NaoEncontrado, ValidacaoDominio
from forja.memoria.contratos import MemoriaIn
from forja.memoria.modelo import Principal
from forja.memoria.rotulagem import MIN_CONFIAVEL, RotulagemServico
from forja.orquestracao.memoria_servico import ServicoMemoria

P = Principal("operador", frozenset({"publico"}))


@pytest.fixture
def corpus(repo):
    s = ServicoMemoria(repo)
    ids = {}
    for chave, titulo, conteudo in [
        ("auth", "Autenticacao por token Bearer", "A API exige cabecalho Authorization com token Bearer comparado em tempo constante."),
        ("backup", "Rotina de backup do banco", "O banco SQLite e copiado pela API de backup online, sem parar o servidor."),
        ("deploy", "Publicacao em producao", "Nunca publicar sem aprovacao explicita do operador."),
    ]:
        ids[chave] = s.criar(P, MemoriaIn(tipo="procedimental", titulo=titulo, resumo=titulo, conteudo=conteudo, tags=[], namespace="publico"))["id"]
    return s, ids


def test_candidatos_unem_baseline_e_busca_nova_sem_ordem_de_ranking(repo, corpus):
    s, ids = corpus
    r = RotulagemServico(repo, s)
    c = r.candidatos(P, "como autenticar com token")
    assert ids["auth"] in [x["id"] for x in c["candidatos"]] and c["namespaces"] == ["publico"]
    assert r.candidatos(P, "como autenticar com token") == c  # embaralhamento deterministico
    with pytest.raises(ValidacaoDominio):
        r.candidatos(P, "x")
    with pytest.raises(ValidacaoDominio):
        r.candidatos(P, "token", ["privado"])  # namespace fora da permissao do usuario


def test_salvar_medir_e_remover(repo, corpus):
    s, ids = corpus
    r = RotulagemServico(repo, s)
    assert r.estado(P)["metricas"] is None
    c = r.candidatos(P, "token bearer na api")
    vistos = [x["id"] for x in c["candidatos"]]
    caso = r.salvar(c["consulta"], [ids["auth"]], vistos, c["namespaces"], "seguranca", 0)
    e = r.estado(P, 3)
    assert e["com_relevantes"] == 1 and e["metricas"]["nova"]["global"]["mrr"] == 1.0
    assert str(MIN_CONFIAVEL) in e["aviso"]  # amostra pequena e dita com clareza
    r.salvar("pergunta sem resposta no corpus", [], vistos, ["publico"], expected_version=1)
    assert r.estado(P)["sem_relevantes"] == 1 and r.estado(P)["metricas"]["nova"]["global"]["casos"] == 1
    with pytest.raises(ConflitoVersao):
        r.remover(caso["id"], 0)
    r.remover(caso["id"], 2)
    with pytest.raises(NaoEncontrado):
        r.remover(caso["id"], 3)


def test_so_marca_o_que_foi_mostrado_e_nao_guarda_conteudo(repo, corpus):
    s, ids = corpus
    r = RotulagemServico(repo, s)
    with pytest.raises(ValidacaoDominio):
        r.salvar("token", [ids["deploy"]], [ids["auth"]], ["publico"])
    r.salvar("token", [ids["auth"]], [ids["auth"]], ["publico"])
    with repo.leitura() as t:
        guardado = str(t.obter(T.Configuracao, "rotulos_busca")["valor"])
        eventos = [e for e in t.listar(T.Evento, ordem=T.Evento.seq, limite=500) if e["tipo"].startswith("busca.rotulo")]
    assert "tempo constante" not in guardado  # so a consulta e IDs, nunca o conteudo da memoria
    assert eventos and all("token" not in str(e["payload"]) for e in eventos)  # evento sem a consulta (pode ser pessoal)


def test_api_de_rotulagem(client):
    assert client.get("/api/v1/busca/rotulagem").json()["rotulados"] == 0
    r = client.post("/api/v1/busca/rotulagem/candidatos", json={"consulta": "qualquer coisa"})
    assert r.status_code == 200 and r.json()["candidatos"] == []
    r = client.post("/api/v1/busca/rotulagem/casos", json={"expected_version": 0, "consulta": "abc", "relevantes": ["X"], "vistos": ["Y"]})
    assert r.status_code == 422
    r = client.post("/api/v1/busca/rotulagem/casos", json={"expected_version": 0, "consulta": "abc", "relevantes": [], "vistos": ["Y"]})
    assert r.status_code == 201
    estado = client.get("/api/v1/busca/rotulagem", params={"k": 3}).json()
    assert estado["rotulados"] == 1 and estado["versao"] == 1
    assert client.delete(f"/api/v1/busca/rotulagem/casos/{estado['casos'][0]['id']}", params={"expected_version": 1}).status_code == 204
    assert client.get("/api/v1/busca/rotulagem", params={"k": 99}).status_code == 422
