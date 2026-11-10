"""Maquina de estados da tarefa (secao 6.2 da orientacao mestra). Pura, sem I/O."""

from __future__ import annotations

from enum import StrEnum

from forja.dominio.erros import TransicaoInvalida


class EstadoTarefa(StrEnum):
    RASCUNHO = "rascunho"
    CLASSIFICADA = "classificada"
    PREPARADA = "preparada"
    AGUARDANDO_DEPENDENCIAS = "aguardando_dependencias"
    PRONTA = "pronta"
    ATRIBUIDA = "atribuida"
    EXECUTANDO = "executando"
    BLOQUEADA = "bloqueada"
    AGUARDANDO_APROVACAO = "aguardando_aprovacao"
    VALIDANDO = "validando"
    CONCLUIDA = "concluida"
    FALHOU = "falhou"
    CANCELADA = "cancelada"
    EXPIRADA = "expirada"


class EstadoExecucao(StrEnum):
    PENDENTE = "pendente"
    EXECUTANDO = "executando"
    PAUSADA = "pausada"
    AGUARDANDO_APROVACAO = "aguardando_aprovacao"
    CONCLUIDA = "concluida"
    FALHOU = "falhou"
    CANCELADA = "cancelada"
    EXPIRADA = "expirada"


E = EstadoTarefa

TERMINAIS = frozenset({E.CONCLUIDA, E.FALHOU, E.CANCELADA, E.EXPIRADA})

TRANSICOES: dict[EstadoTarefa, frozenset[EstadoTarefa]] = {
    E.RASCUNHO: frozenset({E.CLASSIFICADA, E.CANCELADA}),
    E.CLASSIFICADA: frozenset({E.PREPARADA, E.CANCELADA}),
    E.PREPARADA: frozenset({E.AGUARDANDO_DEPENDENCIAS, E.PRONTA, E.CANCELADA}),
    E.AGUARDANDO_DEPENDENCIAS: frozenset({E.PRONTA, E.CANCELADA, E.FALHOU}),
    E.PRONTA: frozenset({E.ATRIBUIDA, E.CANCELADA, E.EXPIRADA}),
    E.ATRIBUIDA: frozenset({E.EXECUTANDO, E.PRONTA, E.CANCELADA}),
    E.EXECUTANDO: frozenset(
        {E.BLOQUEADA, E.AGUARDANDO_APROVACAO, E.VALIDANDO, E.FALHOU, E.CANCELADA, E.EXPIRADA}
    ),
    E.BLOQUEADA: frozenset({E.EXECUTANDO, E.FALHOU, E.CANCELADA, E.EXPIRADA}),
    E.AGUARDANDO_APROVACAO: frozenset({E.EXECUTANDO, E.FALHOU, E.CANCELADA, E.EXPIRADA}),
    E.VALIDANDO: frozenset({E.CONCLUIDA, E.FALHOU, E.EXECUTANDO, E.CANCELADA}),
    E.CONCLUIDA: frozenset(),
    E.FALHOU: frozenset(),
    E.CANCELADA: frozenset(),
    E.EXPIRADA: frozenset(),
}

# Transicoes que somente o orquestrador pode aplicar (nao expostas ao comando manual da API).
RESERVADAS_AO_ORQUESTRADOR = frozenset(
    {
        E.ATRIBUIDA,
        E.EXECUTANDO,
        E.BLOQUEADA,
        E.AGUARDANDO_APROVACAO,
        E.VALIDANDO,
        E.CONCLUIDA,
        E.FALHOU,
        E.EXPIRADA,
        E.AGUARDANDO_DEPENDENCIAS,
        E.PRONTA,
    }
)


def eh_terminal(estado: EstadoTarefa) -> bool:
    return estado in TERMINAIS


def validar_transicao(atual: EstadoTarefa, destino: EstadoTarefa) -> None:
    if destino not in TRANSICOES[atual]:
        raise TransicaoInvalida(f"Transicao {atual.value} -> {destino.value} nao permitida.")
