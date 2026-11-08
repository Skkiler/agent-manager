"""Aprovacao por ACAO: um grupo, uma pergunta, adendo, itens parciais, lembrar, timeout, cancelamento, lote, recuperacao."""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import inspect

from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp
from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.banco import criar_engines, migrar
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.dominio.contratos import (
    DecisaoAprovacaoIn,
    DecisaoLoteIn,
    ObjetivoIn,
    ProjetoIn,
    TarefaIn,
    TransicaoIn,
)
from forja.dominio.erros import ValidacaoDominio
from forja.dominio.estados import EstadoExecucao, EstadoTarefa
from forja.orquestracao.servico import Servico

FAKE = str(Path(__file__).parent / "fakes" / "fake_acp_agent.py")
ET = EstadoTarefa


@pytest.fixture
def mk(repo: RepositorioSqlite, tmp_path: Path):
    criados: list[Servico] = []

    def _mk(cenario: str, espera_aprovacao_s: float = 30.0) -> Servico:
        prov = ProvedorKiroAcp([sys.executable, FAKE, cenario], tmp_path / "ws", timeout_prompt=30,
                               timeout_handshake=10, janela_agrupamento=0.3)
        s = Servico(repo, prov, tmp_path / "art", max_workers=4, espera_aprovacao_s=espera_aprovacao_s)
        criados.append(s)
        return s

    yield _mk
    for s in criados:
        s.encerrar(5)


def _pronta(s: Servico, nome: str) -> dict:
    p, _ = s.criar_projeto(ProjetoIn(nome=nome))
    o, _ = s.criar_objetivo(ObjetivoIn(projeto_id=p["id"], titulo="o"))
    t, _ = s.criar_tarefa(TarefaIn(objetivo_id=o["id"], titulo="analisar", criterios_aceite=["ok"]))
    r = s.transicionar(t["id"], TransicaoIn(para=ET.CLASSIFICADA, expected_version=1))[0]
    return s.transicionar(t["id"], TransicaoIn(para=ET.PREPARADA, expected_version=r["versao_estado"]))[0]


def _iniciar(s: Servico, tarefa: dict) -> dict:
    ex = s.criar_execucao(tarefa["id"])
    s.iniciar_execucao(ex["id"])
    return ex


def _esperar_pendente(s: Servico, minimo: int = 1, timeout: float = 20.0) -> list[dict]:
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        pend = s.listar(T.Aprovacao, estado="pendente")
        if len(pend) >= minimo:
            return pend
        time.sleep(0.05)
    raise AssertionError("nenhum pedido de aprovacao apareceu")


def _decisoes(s: Servico, tarefa_id: str) -> dict:
    ev = s.listar(T.Evidencia, tarefa_id=tarefa_id)[0]
    art = [a for a in s.listar(T.Artefato, tarefa_id=tarefa_id)][0]
    texto = s.obter_artefato(art["id"], com_conteudo=True)["conteudo"]
    m = re.search(r"decisoes=(\{.*?\})", texto)
    assert m, texto
    return {"decisoes": json.loads(m.group(1)), "texto": texto, "evidencia": ev}


def test_grupo_uma_pergunta_com_adendo_e_segredo_negado_sem_perguntar(mk):
    s = mk("multiplas")
    tarefa = _pronta(s, "grp")
    ex = _iniciar(s, tarefa)
    pend = _esperar_pendente(s)
    assert len(pend) == 1, "tres ferramentas simultaneas devem virar UMA pergunta"
    ap = pend[0]
    descr = [i["descricao"] for i in ap["itens"]]
    assert len(descr) == 2, "o .env nao pode nem aparecer como pedido aprovavel"
    assert any(d.startswith("Posso excluir forçadamente") for d in descr)
    assert any(d.startswith("Posso criar ou modificar") for d in descr)
    # enquanto aguarda, o estado e real e visivel
    assert s.obter(T.Tarefa, tarefa["id"])["estado"] == ET.AGUARDANDO_APROVACAO.value
    assert s.obter(T.Execucao, ex["id"])["estado"] == EstadoExecucao.AGUARDANDO_APROVACAO.value

    s.decidir_aprovacao(ap["id"], DecisaoAprovacaoIn(decisao="aprovada", adendo="Use apenas a pasta temporaria."))
    s.aguardar(ex["id"], 30)

    r = _decisoes(s, tarefa["id"])
    assert s.obter(T.Tarefa, tarefa["id"])["estado"] == ET.CONCLUIDA.value
    assert r["decisoes"] == {"910": "accept", "911": "accept", "912": "reject"}  # .env negado automaticamente
    assert "consultas ao operador: 1" in r["evidencia"]["resumo"]
    assert "acompanhamento recebido" in r["texto"] and "pasta temporaria" in r["texto"]  # adendo chegou ao agente
    salvo = s.obter(T.Aprovacao, ap["id"])
    assert salvo["adendo"] == "Use apenas a pasta temporaria." and salvo["decidido_por"] == "operador"
    tipos = [e["tipo"] for e in s.eventos_apos(0, 1000)]
    assert "kiro.permissao_negada_automatica" in tipos and "aprovacao.aprovada" in tipos
    ex_final = s.obter(T.Execucao, ex["id"])
    assert ex_final["resultado"]["consumo"]["chamadas_modelo"] == 2  # prompt + acompanhamento, contados


def test_aprovacao_parcial_aprova_so_o_item_escolhido(mk):
    s = mk("multiplas")
    tarefa = _pronta(s, "parcial")
    ex = _iniciar(s, tarefa)
    ap = _esperar_pendente(s)[0]
    s.decidir_aprovacao(ap["id"], DecisaoAprovacaoIn(decisao="aprovada", itens_aprovados=["910"]))
    s.aguardar(ex["id"], 30)
    assert _decisoes(s, tarefa["id"])["decisoes"] == {"910": "accept", "911": "reject", "912": "reject"}


def test_negar_grupo_nao_cancela_a_tarefa(mk):
    s = mk("multiplas")
    tarefa = _pronta(s, "negar")
    ex = _iniciar(s, tarefa)
    ap = _esperar_pendente(s)[0]
    s.decidir_aprovacao(ap["id"], DecisaoAprovacaoIn(decisao="negada"))
    s.aguardar(ex["id"], 30)
    assert _decisoes(s, tarefa["id"])["decisoes"] == {"910": "reject", "911": "reject", "912": "reject"}
    assert s.obter(T.Tarefa, tarefa["id"])["estado"] == ET.CONCLUIDA.value  # o agente decide como seguir sem a acao


def test_ids_de_item_invalidos_sao_rejeitados(mk):
    s = mk("multiplas")
    tarefa = _pronta(s, "invalido")
    ex = _iniciar(s, tarefa)
    ap = _esperar_pendente(s)[0]
    with pytest.raises(ValidacaoDominio):
        s.decidir_aprovacao(ap["id"], DecisaoAprovacaoIn(decisao="aprovada", itens_aprovados=["nao-existe"]))
    assert s.obter(T.Aprovacao, ap["id"])["estado"] == "pendente"  # nada mudou
    s.decidir_aprovacao(ap["id"], DecisaoAprovacaoIn(decisao="negada"))
    s.aguardar(ex["id"], 30)


def test_lembrar_evita_nova_pergunta_para_acao_identica(mk):
    s = mk("repetida")
    tarefa = _pronta(s, "lembrar")
    ex = _iniciar(s, tarefa)
    ap = _esperar_pendente(s)[0]
    s.decidir_aprovacao(ap["id"], DecisaoAprovacaoIn(decisao="aprovada", lembrar_na_execucao=True))
    s.aguardar(ex["id"], 30)
    assert _decisoes(s, tarefa["id"])["decisoes"]["921"] == "accept"
    assert len(s.listar(T.Aprovacao)) == 1, "a segunda acao identica nao pode gerar nova pergunta"
    assert "kiro.permissao_reutilizada" in [e["tipo"] for e in s.eventos_apos(0, 1000)]


def test_sem_lembrar_pergunta_de_novo(mk):
    s = mk("repetida")
    tarefa = _pronta(s, "nao-lembrar")
    ex = _iniciar(s, tarefa)
    ap = _esperar_pendente(s)[0]
    s.decidir_aprovacao(ap["id"], DecisaoAprovacaoIn(decisao="aprovada"))
    segundo = _esperar_pendente(s)[0]
    assert segundo["id"] != ap["id"]
    s.decidir_aprovacao(segundo["id"], DecisaoAprovacaoIn(decisao="negada"))
    s.aguardar(ex["id"], 30)
    assert _decisoes(s, tarefa["id"])["decisoes"]["921"] == "reject"


def test_timeout_nega_e_nunca_aprova_por_omissao(mk):
    s = mk("multiplas", espera_aprovacao_s=0.6)
    tarefa = _pronta(s, "timeout")
    ex = _iniciar(s, tarefa)
    s.aguardar(ex["id"], 30)
    assert _decisoes(s, tarefa["id"])["decisoes"] == {"910": "reject", "911": "reject", "912": "reject"}
    ap = s.listar(T.Aprovacao)[0]
    assert ap["estado"] == "negada" and ap["decidido_por"] == "sistema:timeout"
    assert "aprovacao.expirada" in [e["tipo"] for e in s.eventos_apos(0, 1000)]
    assert s.obter(T.Tarefa, tarefa["id"])["estado"] == ET.CONCLUIDA.value


def test_cancelar_enquanto_aguarda_aprovacao(mk):
    s = mk("multiplas")
    tarefa = _pronta(s, "cancelar")
    ex = _iniciar(s, tarefa)
    ap = _esperar_pendente(s)[0]
    s.cancelar_execucao(ex["id"])
    s.aguardar(ex["id"], 30)
    assert s.obter(T.Tarefa, tarefa["id"])["estado"] == ET.CANCELADA.value
    assert s.obter(T.Aprovacao, ap["id"])["estado"] == "negada"  # nada fica pendente sem worker


def test_decisao_em_lote_para_varios_pedidos(mk):
    s = mk("multiplas")
    t1, t2 = _pronta(s, "lote-1"), _pronta(s, "lote-2")
    ex1, ex2 = _iniciar(s, t1), _iniciar(s, t2)
    pend = _esperar_pendente(s, minimo=2)
    res = s.decidir_lote(DecisaoLoteIn(ids=[p["id"] for p in pend] + ["AP-inexistente"], decisao="aprovada",
                                       adendo="ok para ambos"))
    assert len(res["resultados"]) == 2 and res["erros"][0]["erro"] == "nao_encontrado"  # falha individual nao aborta
    s.aguardar(ex1["id"], 30)
    s.aguardar(ex2["id"], 30)
    assert all(s.obter(T.Tarefa, t["id"])["estado"] == ET.CONCLUIDA.value for t in (t1, t2))
    assert {a["adendo"] for a in s.listar(T.Aprovacao)} == {"ok para ambos"}


def test_decisao_dupla_conflita(mk):
    s = mk("multiplas")
    tarefa = _pronta(s, "dupla")
    ex = _iniciar(s, tarefa)
    ap = _esperar_pendente(s)[0]
    s.decidir_aprovacao(ap["id"], DecisaoAprovacaoIn(decisao="negada"))
    from forja.dominio.erros import Conflito
    with pytest.raises(Conflito):
        s.decidir_aprovacao(ap["id"], DecisaoAprovacaoIn(decisao="aprovada"))
    s.aguardar(ex["id"], 30)


def test_recuperacao_de_pedido_orfao_apos_reinicio(mk, repo):
    s = mk("multiplas")
    tarefa = _pronta(s, "orfao")
    ex = s.criar_execucao(tarefa["id"])
    # estado pos-crash: worker morreu enquanto aguardava a decisao do operador
    with repo.escrita() as tx:
        tx.atualizar(T.Execucao, ex["id"], estado=EstadoExecucao.AGUARDANDO_APROVACAO.value)
        tx.atualizar_tarefa_condicional(tarefa["id"], ET.PRONTA.value, tarefa["versao_estado"],
                                        estado=ET.AGUARDANDO_APROVACAO.value)
        tx.inserir(T.Aprovacao, id="AP-orfa", tarefa_id=tarefa["id"], execucao_id=ex["id"], acao="x",
                   justificativa="", estado="pendente", origem="durante_execucao",
                   itens=[{"id": "1", "descricao": "Posso x?"}], adendo="", criado_em="2026-01-01T00:00:00Z")
    novo = mk("multiplas")
    assert novo.recuperar()["recuperadas"] == 1
    assert novo.obter(T.Aprovacao, "AP-orfa")["decidido_por"] == "sistema:reinicio"
    assert novo.obter(T.Execucao, ex["id"])["estado"] == EstadoExecucao.PAUSADA.value
    assert novo.obter(T.Tarefa, tarefa["id"])["estado"] == ET.BLOQUEADA.value


def test_adendo_pre_execucao_chega_ao_prompt(mk):
    from forja.adapters.kiro_acp.provedor import montar_prompt
    texto = montar_prompt({"titulo": "t", "criterios_aceite": ["a"], "adendos_operador": ["Nao toque em docs/."]})
    assert "Nao toque em docs/." in texto and "adendos a autorizacao" in texto


def test_aprovacao_pre_execucao_com_adendo_e_entregue(mk):
    s = mk("ok")
    s.provedor.mock = False
    p, _ = s.criar_projeto(ProjetoIn(nome="pre"))
    o, _ = s.criar_objetivo(ObjetivoIn(projeto_id=p["id"], titulo="o"))
    from forja.dominio.contratos import Politicas
    t, _ = s.criar_tarefa(TarefaIn(objetivo_id=o["id"], titulo="a", criterios_aceite=["ok"],
                                   politicas=Politicas(exige_aprovacao=True)))
    r = s.transicionar(t["id"], TransicaoIn(para=ET.CLASSIFICADA, expected_version=1))[0]
    s.transicionar(t["id"], TransicaoIn(para=ET.PREPARADA, expected_version=r["versao_estado"]))
    ex = s.criar_execucao(t["id"])
    s.iniciar_execucao(ex["id"])
    ap = _esperar_pendente(s)[0]
    assert ap["origem"] == "pre_execucao"
    s.decidir_aprovacao(ap["id"], DecisaoAprovacaoIn(decisao="aprovada", adendo="Responda em 3 linhas."))
    s.aguardar(ex["id"], 30)
    assert s.obter(T.Tarefa, t["id"])["estado"] == ET.CONCLUIDA.value
    assert s.obter(T.Aprovacao, ap["id"])["adendo"] == "Responda em 3 linhas."


def test_concorrencia_de_decisoes_so_uma_vence(mk):
    s = mk("multiplas")
    tarefa = _pronta(s, "corrida")
    ex = _iniciar(s, tarefa)
    ap = _esperar_pendente(s)[0]
    resultados: list[str] = []

    def decidir(dec: str) -> None:
        try:
            s.decidir_aprovacao(ap["id"], DecisaoAprovacaoIn(decisao=dec))  # type: ignore[arg-type]
            resultados.append("ok")
        except Exception as e:  # noqa: BLE001
            resultados.append(type(e).__name__)

    ths = [threading.Thread(target=decidir, args=(d,)) for d in ("aprovada", "negada", "aprovada")]
    [t.start() for t in ths]
    [t.join() for t in ths]
    assert resultados.count("ok") == 1 and resultados.count("Conflito") == 2
    s.aguardar(ex["id"], 30)


# ---------------------------------------------------------------- migracao 0002
def test_migracao_0002_preserva_dados_e_bate_com_os_modelos(tmp_path: Path):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine, text

    db = tmp_path / "m.sqlite3"
    migrar(db, "0001")
    eng = create_engine(f"sqlite:///{db.as_posix()}")
    with eng.begin() as c:  # linha pre-existente, antes das novas colunas
        c.execute(text("INSERT INTO projeto VALUES ('P','n','', 'ativo','2026')"))
        c.execute(text("INSERT INTO objetivo VALUES ('O','P','t','',3,'[]','{}','2026')"))
        c.execute(text("INSERT INTO tarefa VALUES ('T','O','P','t','','[]','[]','g','analise','{}','{}','{}','{}','[]',"
                       "'pronta',1,0,'','c','2026','2026')"))
        c.execute(text("INSERT INTO aprovacao VALUES ('AP','T','EX','a','', 'pendente',NULL,NULL,'2026')"))
    eng.dispose()
    migrar(db)
    eng = create_engine(f"sqlite:///{db.as_posix()}")
    with eng.connect() as c:
        row = c.execute(text("SELECT origem, adendo FROM aprovacao WHERE id='AP'")).one()
        assert tuple(row) == ("pre_execucao", "")
        diff = compare_metadata(MigrationContext.configure(c), T.Base.metadata)
    assert diff == [], f"modelos e migracoes divergem: {diff}"
    assert {"origem", "itens", "escopo", "adendo"} <= {c["name"] for c in inspect(eng).get_columns("aprovacao")}
    eng.dispose()
    w, r = criar_engines(db)
    RepositorioSqlite(w, r).fechar()
