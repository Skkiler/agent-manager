"""Testes puros da maquina de estados (sem I/O)."""

from __future__ import annotations

import pytest

from forja.dominio.erros import TransicaoInvalida
from forja.dominio.estados import (
    TERMINAIS,
    TRANSICOES,
    EstadoTarefa,
    eh_terminal,
    validar_transicao,
)

E = EstadoTarefa


def test_todos_estados_tem_regra():
    assert set(TRANSICOES) == set(E)


def test_terminais_sem_saida():
    for term in TERMINAIS:
        assert TRANSICOES[term] == frozenset()
        assert eh_terminal(term)


def test_destinos_sao_estados_validos():
    for destinos in TRANSICOES.values():
        for d in destinos:
            assert isinstance(d, EstadoTarefa)


def test_transicao_valida_nao_levanta():
    validar_transicao(E.RASCUNHO, E.CLASSIFICADA)
    validar_transicao(E.VALIDANDO, E.CONCLUIDA)


def test_sequencia_impossivel_rejeitada():
    with pytest.raises(TransicaoInvalida):
        validar_transicao(E.RASCUNHO, E.CONCLUIDA)
    with pytest.raises(TransicaoInvalida):
        validar_transicao(E.CONCLUIDA, E.EXECUTANDO)
