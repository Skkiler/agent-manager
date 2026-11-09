"""Quadro de comunicacao (blackboard) e painel de controle do master."""

from __future__ import annotations

import shutil
import threading
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.adapters.sqlite import tabelas as T
from forja.config import Configuracoes
from forja.dominio.erros import Conflito, NaoEncontrado
from forja.dominio.quadro import MensagemIn
from forja.orquestracao.quadro_servico import QuadroServico
from forja.servidor.app import criar_app

TOKEN = "token-de-teste-com-tamanho-suficiente"
FALSO_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def msg(**kw) -> MensagemIn:
    base = dict(origem="agente:analista", destino="master", tipo="resultado", prioridade=3, assunto="Analise pronta",
                payload={"resumo": "ok"}, referencias=["artefato:abc123"])
    base.update(kw)
    return MensagemIn(**base)


@pytest.fixture
def q(repo, relogio) -> QuadroServico:
    return QuadroServico(repo, relogio)


# ---------------------------------------------------------------- contrato


@pytest.mark.parametrize(
    "ruim",
    [
        dict(tipo="comando"),  # agente nao comanda
        dict(origem="agente:a", destino="agente:a", tipo="evento"),  # origem == destino
        dict(destino="todos", tipo="pergunta"),  # difusao so evento/apontamento
        dict(origem="sistema", tipo="comando", destino="master"),
        dict(origem="Agente Estranho!"),  # formato da origem
        dict(destino="qualquer"),
        dict(prioridade=0), dict(prioridade=6),
        dict(assunto=""), dict(assunto="x" * 121),
        dict(payload={"texto": "x" * 4001}),  # envie referencias, nao conteudo
        dict(referencias=["http://externo/x"]),
        dict(referencias=["arquivo:a"] * 21),
        dict(expira_em_segundos=10),
        dict(campo_extra=1),
    ],
)
def test_mensagem_malformada_e_recusada(ruim):
    with pytest.raises(ValidationError):
        msg(**ruim)


def test_master_e_operador_podem_comandar_e_sistema_pode_difundir_evento():
    assert msg(origem="master", destino="agente:analista", tipo="comando").tipo == "comando"
    assert msg(origem="operador", destino="agente:analista", tipo="comando")
    assert msg(origem="sistema", destino="todos", tipo="evento")


# ---------------------------------------------------------------- publicar / idempotencia


def test_publicar_sanitiza_e_nao_vaza_no_evento(q, repo):
    m, criada = q.publicar(msg(assunto=f"chave {FALSO_TOKEN}", payload={"token": FALSO_TOKEN, "ok": 1}))
    assert criada and m["estado"] == "pendente" and m["id"].startswith("QD")
    assert FALSO_TOKEN not in str(m)
    with repo.leitura() as t:
        eventos = t.eventos_apos(0)
    ev = next(e for e in eventos if e["tipo"] == "quadro.mensagem_publicada")
    assert set(ev["payload"]) == {"mensagem_id", "tipo", "prioridade", "destino", "ator"}  # so ids e metadados


def test_reenvio_com_mesma_origem_e_dedup_devolve_a_original(q):
    a, c1 = q.publicar(msg(dedup_key="k1"))
    b, c2 = q.publicar(msg(dedup_key="k1", assunto="outra coisa"))
    assert (c1, c2) == (True, False) and a["id"] == b["id"] and b["assunto"] == "Analise pronta"
    assert len(q.listar()) == 1


def test_dedup_e_isolada_por_origem_e_nao_permite_suprimir_mensagem_alheia(q):
    q.publicar(msg(origem="agente:a", dedup_key="k"))
    _, criada = q.publicar(msg(origem="agente:b", dedup_key="k"))
    assert criada


def test_dedup_concorrente_cria_uma_unica_mensagem(q):
    resultados = []

    def enviar():
        resultados.append(q.publicar(msg(dedup_key="corrida"))[1])

    ts = [threading.Thread(target=enviar) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert resultados.count(True) == 1 and len(q.listar()) == 1


def test_publicar_com_tarefa_inexistente_falha(q):
    with pytest.raises(NaoEncontrado):
        q.publicar(msg(tarefa_id="T-nao-existe"))


# ---------------------------------------------------------------- listar / retirar / resolver


def test_listar_ordena_por_prioridade_depois_por_antiguidade(q, relogio):
    q.publicar(msg(assunto="p3-a", prioridade=3))
    relogio.avancar(1)
    q.publicar(msg(assunto="p1", prioridade=1))
    relogio.avancar(1)
    q.publicar(msg(assunto="p3-b", prioridade=3))
    assert [m["assunto"] for m in q.listar()] == ["p1", "p3-a", "p3-b"]
    assert [m["assunto"] for m in q.listar(prioridade_max=1)] == ["p1"]


def test_retirar_entrega_uma_vez_por_prioridade_e_respeita_o_destino(q):
    q.publicar(msg(destino="agente:x", assunto="baixa", prioridade=5, tipo="pergunta"))
    q.publicar(msg(destino="agente:x", assunto="alta", prioridade=1, tipo="pergunta"))
    q.publicar(msg(destino="master", assunto="do master"))
    primeira = q.retirar("agente:x", limite=1)
    assert [m["assunto"] for m in primeira] == ["alta"]
    segunda = q.retirar("agente:x")
    assert [m["assunto"] for m in segunda] == ["baixa"]
    assert q.retirar("agente:x") == []  # nada e entregue duas vezes
    assert [m["assunto"] for m in q.retirar("master")] == ["do master"]
    assert {m["estado"] for m in q.listar(destino="agente:x")} == {"entregue"}


def test_difusao_chega_a_todos_sem_ser_consumida(q):
    q.publicar(msg(origem="sistema", destino="todos", tipo="evento", assunto="manutencao"))
    assert [m["assunto"] for m in q.retirar("agente:a")] == ["manutencao"]
    assert [m["assunto"] for m in q.retirar("agente:b")] == ["manutencao"]


def test_listar_destino_todos_nao_duplica_a_difusao(q):
    q.publicar(msg(origem="sistema", destino="todos", tipo="evento", assunto="aviso"))
    q.publicar(msg(origem="sistema", destino="agente:a", tipo="evento", assunto="so para a"))
    assert [m["assunto"] for m in q.listar(destino="todos")] == ["aviso"]
    assert sorted(m["assunto"] for m in q.listar(destino="agente:a")) == ["aviso", "so para a"]


def test_resolver_registra_ator_e_nota_e_nao_resolve_duas_vezes(q):
    m, _ = q.publicar(msg())
    r = q.resolver(m["id"], "joao", f"feito {FALSO_TOKEN}")
    assert r["estado"] == "resolvida" and r["resolvida_por"] == "joao" and FALSO_TOKEN not in r["nota_resolucao"]
    with pytest.raises(Conflito):
        q.resolver(m["id"])
    with pytest.raises(NaoEncontrado):
        q.resolver("QD-nao-existe")


def test_mensagens_expiram_e_nao_sao_entregues(q, relogio):
    q.publicar(msg(expira_em_segundos=60, assunto="efemera"))
    q.publicar(msg(assunto="duradoura"))
    relogio.avancar(61)
    assert q.expirar() == 1
    assert [m["assunto"] for m in q.retirar("master")] == ["duradoura"]
    assert q.listar(estado="expirada")[0]["assunto"] == "efemera"
    assert q.expirar() == 0  # idempotente


# ---------------------------------------------------------------- painel de controle


def _tarefa(repo, estado: str, n: int = 1) -> str:
    with repo.escrita() as t:
        t.inserir(T.Projeto, id=f"P{n}", nome=f"p{n}", descricao="", estado="ativo", criado_em="2026")
        t.inserir(T.Objetivo, id=f"O{n}", projeto_id=f"P{n}", titulo="o", descricao="", prioridade=3,
                  criterios_sucesso=[], orcamento={}, criado_em="2026")
        t.inserir(T.Tarefa, id=f"T{n}", objetivo_id=f"O{n}", projeto_id=f"P{n}", titulo=f"tarefa {n}", descricao="",
                  criterios_aceite=["x"], dependencias=[], especialidade="g", modo="analise", recursos={}, orcamento={},
                  politicas={}, entrada={}, contexto_refs=[], estado=estado, versao_estado=1, tentativas=1,
                  motivo_estado="", correlation_id="c", criado_em="2026", atualizado_em="2026")
    return f"T{n}"


def test_painel_resume_o_que_exige_atencao_do_master(q, repo, relogio):
    tid = _tarefa(repo, "bloqueada")
    with repo.escrita() as t:
        agora = relogio.agora()
        t.inserir(T.Execucao, id="E1", tarefa_id=tid, estado="executando", agente_id="a", tentativa=1, checkpoint={},
                  resultado=None, deadline=None, iniciado_em=(agora - timedelta(hours=2)).isoformat(),
                  finalizado_em=None, correlation_id="c", criado_em="2026")
        t.inserir(T.Aprovacao, id="A1", execucao_id="E1", tarefa_id=tid, acao="apagar build", justificativa="",
                  estado="pendente", criado_em="2026", origem="pre_execucao", itens=[])
    q.publicar(msg(assunto="critico", prioridade=1, tipo="apontamento"))
    q.publicar(msg(assunto="rotina", prioridade=4))
    p = q.painel_controle()
    assert p["quadro"]["abertas"] == 2 and p["quadro"]["por_prioridade"] == {1: 1, 4: 1}
    assert [m["assunto"] for m in p["quadro"]["urgentes"]] == ["critico"]
    assert p["tarefas"]["aguardando_decisao"][0]["id"] == tid and p["tarefas"]["por_estado"] == {"bloqueada": 1}
    assert p["aprovacoes_pendentes"][0]["acao"] == "apagar build"
    assert p["execucoes_paradas"][0]["id"] == "E1"
    assert len(p["alertas"]) == 4


def test_painel_vazio_nao_tem_alertas(q):
    p = q.painel_controle()
    assert p["alertas"] == [] and p["quadro"]["abertas"] == 0


# ---------------------------------------------------------------- API


@pytest.fixture
def cli(tmp_path: Path, _db_migrado: Path) -> Iterator[TestClient]:
    (tmp_path / "data").mkdir()
    shutil.copyfile(_db_migrado, tmp_path / "data" / "forja.sqlite3")
    cfg = Configuracoes(_env_file=None, app_data_dir=tmp_path / "data", app_log_dir=tmp_path / "logs",  # type: ignore[call-arg]
                        app_api_token=TOKEN, app_allowed_hosts="testserver")
    with TestClient(criar_app(cfg, AgenteMock()), headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c


CORPO = {"origem": "agente:analista", "destino": "master", "tipo": "resultado", "assunto": "pronto", "dedup_key": "d1"}


def test_api_fluxo_publicar_retirar_resolver_e_painel(cli):
    r1 = cli.post("/api/v1/quadro", json=CORPO)
    r2 = cli.post("/api/v1/quadro", json=CORPO)
    assert (r1.status_code, r2.status_code) == (201, 200) and r1.json()["id"] == r2.json()["id"]
    assert cli.get("/api/v1/quadro", params={"destino": "master", "prioridade_max": 3}).json()[0]["assunto"] == "pronto"
    retiradas = cli.post("/api/v1/quadro/retirar", params={"destino": "master"}).json()
    assert [m["id"] for m in retiradas] == [r1.json()["id"]]
    assert cli.post(f"/api/v1/quadro/{r1.json()['id']}/resolver", json={"nota": "ok"}).json()["estado"] == "resolvida"
    assert cli.post(f"/api/v1/quadro/{r1.json()['id']}/resolver", json={}).status_code == 409
    assert cli.get("/api/v1/controle/painel").json()["quadro"]["abertas"] == 0


@pytest.mark.parametrize("corpo", [{**CORPO, "tipo": "comando"}, {**CORPO, "prioridade": 9}, {**CORPO, "x": 1}, {}])
def test_api_recusa_mensagem_malformada_com_422(cli, corpo):
    assert cli.post("/api/v1/quadro", json=corpo).status_code == 422


def test_api_filtros_invalidos_e_autenticacao(cli):
    assert cli.get("/api/v1/quadro", params={"destino": "../x"}).status_code == 422
    assert cli.get("/api/v1/quadro", params={"estado": "qualquer"}).status_code == 422
    assert cli.post("/api/v1/quadro/QD-x/resolver", json={}).status_code == 404
    sem = TestClient(cli.app, headers={"Host": "testserver"})
    assert sem.get("/api/v1/quadro").status_code in (401, 403)
    assert sem.get("/api/v1/controle/painel").status_code in (401, 403)
