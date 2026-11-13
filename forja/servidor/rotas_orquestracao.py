"""Rotas das melhorias do orquestrador: desfazer por tarefa, pastas isoladas, custo, roteamento aprendido, oficina e replay.
Apenas traducao HTTP <-> servicos (regras e protecoes vivem nos servicos)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict

from forja.adapters.sqlite import tabelas as T
from forja.servidor.rotas import ATOR, ID, autenticar

rx = APIRouter(prefix="/api/v1", dependencies=[Depends(autenticar)])


class DesfazerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    forcar: bool = False  # sobrescreve arquivos alterados depois da execucao (pede confirmacao na tela)


@rx.get("/tarefas/{id_}/restauracao")
def pontos_da_tarefa(id_: ID, request: Request) -> list[dict[str, Any]]:
    """Pontos de restauracao da tarefa: o que cada execucao alterou, criou e apagou (so caminhos relativos)."""
    request.app.state.servico.obter(T.Tarefa, id_)  # 404 se a tarefa nao existe
    return request.app.state.restauracao.listar(id_)


@rx.post("/restauracao/{id_}/desfazer")
def desfazer(id_: ID, d: DesfazerIn, request: Request) -> dict[str, Any]:
    return request.app.state.restauracao.desfazer(id_, d.forcar, ATOR)


@rx.get("/isolamentos")
def isolamentos(request: Request, incluir_removidas: bool = False) -> list[dict[str, Any]]:
    return request.app.state.isolamento.listar(incluir_removidas)


@rx.delete("/isolamentos/{id_}")
def remover_isolamento(id_: ID, request: Request) -> dict[str, Any]:
    """Remove a copia isolada (git worktree remove). O branch continua no repositorio."""
    return request.app.state.isolamento.remover(id_)


@rx.get("/custos")
def custos(request: Request, dias: Annotated[int, Query(ge=1, le=365)] = 30) -> dict[str, Any]:
    return request.app.state.custos.painel(dias)


@rx.get("/roteamento/estatisticas")
def estatisticas_rota(request: Request) -> dict[str, Any]:
    a = request.app.state.aprendizado
    return {"ativo": a.ativo, "por_nivel": a.por_nivel(), "linhas": a.resumo()}


@rx.get("/oficina")
def oficina(request: Request, projeto_id: ID | None = None) -> dict[str, Any]:
    return request.app.state.oficina.cena(projeto_id)


@rx.get("/execucoes/{id_}/replay")
def replay(id_: ID, request: Request) -> dict[str, Any]:
    return request.app.state.oficina.replay(id_)
