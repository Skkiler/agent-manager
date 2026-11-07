"""Testes de integracao do nucleo: fluxo ponta a ponta, concorrencia, orcamento, locks, recuperacao."""

from __future__ import annotations

import pytest

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.dominio.contratos import (
    DecisaoAprovacaoIn,
    ObjetivoIn,
    Orcamento,
    Politicas,
    ProjetoIn,
    Recursos,
    TarefaIn,
    TransicaoIn,
)
from forja.dominio.erros import (
    ConflitoVersao,
    LockIndisponivel,
    TransicaoReservada,
    ValidacaoDominio,
)
from forja.dominio.estados import EstadoExecucao, EstadoTarefa
from forja.orquestracao.servico import Servico

ET = EstadoTarefa


def _preparar(s: Servico, cenario: str = "sucesso", **kw) -> dict:
    p, _ = s.criar_projeto(ProjetoIn(nome=f"proj-{cenario}-{id(kw)}"))
    o, _ = s.criar_objetivo(ObjetivoIn(projeto_id=p["id"], titulo="obj"))
    kw.setdefault("entrada", {"mock_cenario": cenario, "mock_passos": 2})
    t, _ = s.criar_tarefa(TarefaIn(objetivo_id=o["id"], titulo="t", criterios_aceite=["ok"], **kw))
    r = s.transicionar(t["id"], TransicaoIn(para=ET.CLASSIFICADA, expected_version=t["versao_estado"]))[0]
    return s.transicionar(t["id"], TransicaoIn(para=ET.PREPARADA, expected_version=r["versao_estado"]))[0]


def _executar_ate_fim(s: Servico, tarefa_id: str) -> dict:
    ex = s.criar_execucao(tarefa_id)
    s.iniciar_execucao(ex["id"])
    s.aguardar(ex["id"], timeout=10)
    return s.obter(T.Tarefa, tarefa_id)


def test_fluxo_ponta_a_ponta_sucesso(servico: Servico):
    tarefa = _preparar(servico, "sucesso")
    assert tarefa["estado"] == ET.PRONTA.value
    final = _executar_ate_fim(servico, tarefa["id"])
    assert final["estado"] == ET.CONCLUIDA.value
    evids = servico.listar(T.Evidencia, tarefa_id=tarefa["id"])
    assert evids and all(e["simulada"] for e in evids)  # evidencia de mock e sempre simulada
    arts = servico.listar(T.Artefato, tarefa_id=tarefa["id"])
    assert arts and servico.obter_artefato(arts[0]["id"], com_conteudo=True)["conteudo"]


def test_cenario_falha(servico: Servico):
    tarefa = _preparar(servico, "falha")
    final = _executar_ate_fim(servico, tarefa["id"])
    assert final["estado"] == ET.FALHOU.value


def test_cenario_bloqueio_e_retomada(servico: Servico):
    tarefa = _preparar(servico, "bloqueio")
    final = _executar_ate_fim(servico, tarefa["id"])
    assert final["estado"] == ET.BLOQUEADA.value
    ex = servico.listar(T.Execucao, tarefa_id=tarefa["id"])[0]
    assert ex["estado"] == EstadoExecucao.PAUSADA.value


def test_idempotencia_repete_resposta(servico: Servico):
    a, nova1 = servico.criar_projeto(ProjetoIn(nome="idem"), chave="k1")
    b, nova2 = servico.criar_projeto(ProjetoIn(nome="idem"), chave="k1")
    assert nova1 is False and nova2 is True
    assert a["id"] == b["id"]


def test_idempotencia_corpo_diferente_conflita(servico: Servico):
    servico.criar_projeto(ProjetoIn(nome="idem-a"), chave="k2")
    with pytest.raises(ValidacaoDominio):
        servico.criar_projeto(ProjetoIn(nome="idem-b"), chave="k2")


def test_conflito_versao(servico: Servico):
    tarefa = _preparar(servico, "sucesso")
    with pytest.raises(ConflitoVersao):
        servico.transicionar(tarefa["id"], TransicaoIn(para=ET.CANCELADA, expected_version=999))


def test_transicao_reservada_rejeitada(servico: Servico):
    tarefa = _preparar(servico, "sucesso")
    with pytest.raises(TransicaoReservada):
        servico.transicionar(tarefa["id"], TransicaoIn(para=ET.EXECUTANDO, expected_version=tarefa["versao_estado"]))


def test_duas_execucoes_concorrentes_rejeitadas(servico: Servico):
    tarefa = _preparar(servico, "sucesso", entrada={"mock_cenario": "sucesso", "mock_passos": 4, "mock_passo_ms": 50})
    ex1 = servico.criar_execucao(tarefa["id"])
    servico.iniciar_execucao(ex1["id"])
    from forja.dominio.erros import Conflito
    with pytest.raises(Conflito):
        servico.criar_execucao(tarefa["id"])
    servico.aguardar(ex1["id"], timeout=10)


def test_lock_de_recurso_bloqueia_sobreposicao(servico: Servico):
    # duas tarefas no mesmo projeto disputando o mesmo arquivo de escrita
    p, _ = servico.criar_projeto(ProjetoIn(nome="locks"))
    o, _ = servico.criar_objetivo(ObjetivoIn(projeto_id=p["id"], titulo="o"))
    rec = Recursos(escrita=["backend/app/x.py"])
    t1, _ = servico.criar_tarefa(TarefaIn(objetivo_id=o["id"], titulo="t1", criterios_aceite=["ok"], recursos=rec,
                                          entrada={"mock_cenario": "sucesso", "mock_passos": 6, "mock_passo_ms": 60}))
    t2, _ = servico.criar_tarefa(TarefaIn(objetivo_id=o["id"], titulo="t2", criterios_aceite=["ok"], recursos=rec))
    for t in (t1, t2):
        r = servico.transicionar(t["id"], TransicaoIn(para=ET.CLASSIFICADA, expected_version=1))[0]
        servico.transicionar(t["id"], TransicaoIn(para=ET.PREPARADA, expected_version=r["versao_estado"]))
    ex1 = servico.criar_execucao(t1["id"])
    servico.iniciar_execucao(ex1["id"])
    ex2 = servico.criar_execucao(t2["id"])
    with pytest.raises(LockIndisponivel):
        servico.iniciar_execucao(ex2["id"])
    servico.aguardar(ex1["id"], timeout=10)


def test_orcamento_max_tentativas(servico: Servico):
    tarefa = _preparar(servico, "falha", orcamento=Orcamento(max_tentativas=1))
    _executar_ate_fim(servico, tarefa["id"])
    atual = servico.obter(T.Tarefa, tarefa["id"])
    assert atual["estado"] == ET.FALHOU.value  # terminal; nao ha segunda execucao


def test_aprovacao_obrigatoria(servico: Servico):
    tarefa = _preparar(servico, "sucesso", politicas=Politicas(exige_aprovacao=True))
    ex = servico.criar_execucao(tarefa["id"])
    servico.iniciar_execucao(ex["id"])
    t = servico.obter(T.Tarefa, tarefa["id"])
    assert t["estado"] == ET.AGUARDANDO_APROVACAO.value
    ap = servico.listar(T.Aprovacao, estado="pendente")[0]
    servico.decidir_aprovacao(ap["id"], DecisaoAprovacaoIn(decisao="aprovada"))
    servico.aguardar(ex["id"], timeout=10)
    assert servico.obter(T.Tarefa, tarefa["id"])["estado"] == ET.CONCLUIDA.value


def test_aprovacao_negada_cancela(servico: Servico):
    tarefa = _preparar(servico, "sucesso", politicas=Politicas(exige_aprovacao=True))
    ex = servico.criar_execucao(tarefa["id"])
    servico.iniciar_execucao(ex["id"])
    ap = servico.listar(T.Aprovacao, estado="pendente")[0]
    servico.decidir_aprovacao(ap["id"], DecisaoAprovacaoIn(decisao="negada"))
    assert servico.obter(T.Tarefa, tarefa["id"])["estado"] == ET.CANCELADA.value


def test_dependencias_desbloqueiam(servico: Servico):
    p, _ = servico.criar_projeto(ProjetoIn(nome="dep"))
    o, _ = servico.criar_objetivo(ObjetivoIn(projeto_id=p["id"], titulo="o"))
    t1, _ = servico.criar_tarefa(TarefaIn(objetivo_id=o["id"], titulo="base", criterios_aceite=["ok"],
                                          entrada={"mock_cenario": "sucesso", "mock_passos": 1}))
    t2, _ = servico.criar_tarefa(TarefaIn(objetivo_id=o["id"], titulo="dependente", criterios_aceite=["ok"],
                                          dependencias=[t1["id"]], entrada={"mock_cenario": "sucesso", "mock_passos": 1}))
    for t in (t1, t2):
        r = servico.transicionar(t["id"], TransicaoIn(para=ET.CLASSIFICADA, expected_version=1))[0]
        servico.transicionar(t["id"], TransicaoIn(para=ET.PREPARADA, expected_version=r["versao_estado"]))
    assert servico.obter(T.Tarefa, t2["id"])["estado"] == ET.AGUARDANDO_DEPENDENCIAS.value
    _executar_ate_fim(servico, t1["id"])
    assert servico.obter(T.Tarefa, t2["id"])["estado"] == ET.PRONTA.value


def test_dependencia_pertence_a_outro_projeto(servico: Servico):
    p1, _ = servico.criar_projeto(ProjetoIn(nome="pa"))
    p2, _ = servico.criar_projeto(ProjetoIn(nome="pb"))
    o1, _ = servico.criar_objetivo(ObjetivoIn(projeto_id=p1["id"], titulo="o"))
    o2, _ = servico.criar_objetivo(ObjetivoIn(projeto_id=p2["id"], titulo="o"))
    t1, _ = servico.criar_tarefa(TarefaIn(objetivo_id=o1["id"], titulo="t", criterios_aceite=["ok"]))
    with pytest.raises(ValidacaoDominio):
        servico.criar_tarefa(TarefaIn(objetivo_id=o2["id"], titulo="t", criterios_aceite=["ok"],
                                      dependencias=[t1["id"]]))


def test_recuperacao_pos_crash(servico: Servico, repo: RepositorioSqlite):
    tarefa = _preparar(servico, "sucesso")
    ex = servico.criar_execucao(tarefa["id"])
    # simula estado pos-crash: execucao 'executando' sem worker no processo
    with repo.escrita() as tx:
        tx.atualizar(T.Execucao, ex["id"], estado=EstadoExecucao.EXECUTANDO.value)
        ok = tx.atualizar_tarefa_condicional(tarefa["id"], ET.PRONTA.value, tarefa["versao_estado"],
                                             estado=ET.EXECUTANDO.value)
        assert ok
    novo = Servico(repo, AgenteMock(), servico.artefatos_dir)
    resumo = novo.recuperar()
    novo.encerrar(timeout=5)
    assert resumo["recuperadas"] == 1
    assert servico.obter(T.Execucao, ex["id"])["estado"] == EstadoExecucao.PAUSADA.value
    assert servico.obter(T.Tarefa, tarefa["id"])["estado"] == ET.BLOQUEADA.value


def test_expiracao_por_deadline(servico: Servico, relogio):
    tarefa = _preparar(servico, "bloqueio", orcamento=Orcamento(max_duracao_segundos=1))
    final = _executar_ate_fim(servico, tarefa["id"])  # bloqueia
    assert final["estado"] == ET.BLOQUEADA.value
    relogio.avancar(3600)
    n = servico.expirar_vencidas()
    assert n == 1
    assert servico.obter(T.Tarefa, tarefa["id"])["estado"] == ET.EXPIRADA.value
