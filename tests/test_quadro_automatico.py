"""4.14: o orquestrador publica no quadro o desfecho que exige atencao (decisao, falha, resultado), de forma idempotente e sem
nunca alterar o resultado da execucao se o quadro falhar."""

from __future__ import annotations

import pytest

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.dominio.estados import EstadoExecucao as EE
from forja.dominio.estados import EstadoTarefa as ET
from forja.orquestracao.quadro_servico import QuadroServico
from forja.orquestracao.servico import Servico, _aviso_quadro
from tests.test_servico import _executar_ate_fim, _preparar


@pytest.fixture
def quadro(servico: Servico, repo: RepositorioSqlite) -> QuadroServico:
    servico.quadro = QuadroServico(repo)
    return servico.quadro


def _msgs(quadro: QuadroServico) -> list[dict]:
    return quadro.listar()


def test_conclusao_publica_evento_para_o_master(servico: Servico, quadro: QuadroServico):
    t = _preparar(servico, "sucesso")
    _executar_ate_fim(servico, t["id"])
    m = [x for x in _msgs(quadro) if x["tarefa_id"] == t["id"]]
    assert len(m) == 1 and m[0]["tipo"] == "evento" and m[0]["destino"] == "master" and m[0]["origem"] == "sistema"
    assert any(r.startswith("execucao:") for r in m[0]["referencias"])


def test_falha_publica_apontamento_prioritario(servico: Servico, quadro: QuadroServico):
    t = _preparar(servico, "falha")
    _executar_ate_fim(servico, t["id"])
    m = [x for x in _msgs(quadro) if x["tarefa_id"] == t["id"]]
    assert len(m) == 1 and m[0]["tipo"] == "apontamento" and m[0]["prioridade"] == 1


def test_bloqueio_apontamento_ao_operador(servico: Servico, quadro: QuadroServico):
    t = _preparar(servico, "bloqueio")
    _executar_ate_fim(servico, t["id"])
    m = [x for x in _msgs(quadro) if x["tarefa_id"] == t["id"]]
    assert len(m) == 1 and m[0]["tipo"] == "apontamento" and m[0]["destino"] == "operador" and m[0]["prioridade"] == 2


def test_republicar_o_mesmo_desfecho_nao_duplica(servico: Servico, quadro: QuadroServico):
    t = _preparar(servico, "sucesso")
    _executar_ate_fim(servico, t["id"])
    ex = servico.listar(T.Execucao, tarefa_id=t["id"])[0]
    servico._avisar_quadro(ex["id"])
    servico._avisar_quadro(ex["id"])
    assert len([x for x in _msgs(quadro) if x["tarefa_id"] == t["id"]]) == 1


def test_falha_do_quadro_nao_altera_o_resultado(servico: Servico):
    class Quebrado:
        def publicar(self, *a, **k):
            raise RuntimeError("quadro indisponivel")

    servico.quadro = Quebrado()
    t = _preparar(servico, "sucesso")
    assert _executar_ate_fim(servico, t["id"])["estado"] == ET.CONCLUIDA.value


def test_sem_quadro_nada_acontece(servico: Servico):
    assert servico.quadro is None
    t = _preparar(servico, "sucesso")
    assert _executar_ate_fim(servico, t["id"])["estado"] == ET.CONCLUIDA.value


def test_aviso_nao_vaza_segredo_do_resumo():
    tarefa = {"id": "T-1", "titulo": "x", "estado": ET.FALHOU.value}
    m = _aviso_quadro(EE.FALHOU.value, tarefa, "EX-1", "erro com Bearer abcdefghijklmnop1234567890 no meio")
    assert m is not None and "abcdefghijklmnop1234567890" not in str(m.payload)
    assert _aviso_quadro(EE.CANCELADA.value, tarefa, "EX-1", "") is None  # cancelar e ato do proprio operador: sem aviso
    assert _aviso_quadro(EE.PAUSADA.value, {**tarefa, "estado": ET.EXECUTANDO.value}, "EX-1", "") is None
