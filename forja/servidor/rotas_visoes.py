"""Rotas de visoes para a interface: Kanban de tarefas, grafo do segundo cerebro e backlinks. So leitura."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from forja.orquestracao.grafo_servico import GrafoServico
from forja.orquestracao.visoes import VisaoKanban
from forja.servidor.rotas import ID, autenticar
from forja.servidor.rotas_memoria import Pr

rv = APIRouter(prefix="/api/v1", dependencies=[Depends(autenticar)])


def _kanban(request: Request) -> VisaoKanban:
    return request.app.state.kanban


def _grafo(request: Request) -> GrafoServico:
    return request.app.state.grafo


@rv.get("/kanban")
def kanban(v: Annotated[VisaoKanban, Depends(_kanban)], projeto_id: ID | None = None,
           objetivo_id: ID | None = None) -> dict[str, Any]:
    return v.montar(projeto_id, objetivo_id)


@rv.get("/conhecimento/grafo")
def grafo(g: Annotated[GrafoServico, Depends(_grafo)], p: Pr,
          namespace: Annotated[list[str] | None, Query(max_length=10)] = None,
          q: Annotated[str, Query(max_length=200)] = "",
          limite: Annotated[int, Query(ge=1, le=500)] = 200,
          vizinhos: Annotated[int, Query(ge=0, le=2)] = 1,
          incluir_inativas: bool = False) -> dict[str, Any]:
    return g.grafo(p, namespace or ["publico"], q, limite, vizinhos, incluir_inativas)


@rv.get("/memorias/{id_}/links")
def links(id_: ID, g: Annotated[GrafoServico, Depends(_grafo)], p: Pr) -> dict[str, Any]:
    return g.links(p, id_)

