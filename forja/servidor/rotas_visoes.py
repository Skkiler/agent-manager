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



# ------------------------------------------------------------------ 4.22: ligacoes tipadas criadas pela tela
from fastapi import Response  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field  # noqa: E402

from forja.memoria.modelo import ARESTAS  # noqa: E402
from forja.servidor.rotas import ATOR  # noqa: E402


class LigacaoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origem: Annotated[str, Field(min_length=1, max_length=64)]
    destino: Annotated[str, Field(min_length=1, max_length=64)]
    tipo: Annotated[str, Field(min_length=1, max_length=32)]
    nota: Annotated[str, Field(max_length=300)] = ""


@rv.get("/conhecimento/tipos-de-ligacao")
def tipos_ligacao() -> list[str]:
    return sorted(ARESTAS)


@rv.post("/conhecimento/ligacoes", status_code=201)
def criar_ligacao(d: LigacaoIn, request: Request, p: Pr) -> dict[str, Any]:
    return request.app.state.grafo.ligar(p, d.origem, d.destino, d.tipo, d.nota, ATOR)


@rv.delete("/conhecimento/ligacoes/{id_}", status_code=204)
def remover_ligacao(id_: ID, request: Request, p: Pr) -> Response:
    request.app.state.grafo.desligar(p, id_)
    return Response(status_code=204)
