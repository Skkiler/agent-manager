"""Rotas de memoria / segundo cerebro. Apenas traducao HTTP <-> ServicoMemoria; ACL e regras vivem no servico."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from forja.memoria.contratos import (
    ArestaIn,
    IngerirIn,
    MemoriaAtualizaIn,
    MemoriaIn,
    NoIn,
    ResolverConflitoIn,
    RevalidarIn,
    TransicaoMemoriaIn,
    ValidarIn,
    VincularEvidenciaIn,
)
from forja.memoria.modelo import Principal, TipoMemoria
from forja.orquestracao.memoria_servico import ServicoMemoria
from forja.servidor.rotas import ATOR, ID, autenticar

rm = APIRouter(prefix="/api/v1", dependencies=[Depends(autenticar)])


def _memoria(request: Request) -> ServicoMemoria:
    return request.app.state.memoria


def _principal(request: Request) -> Principal:
    return Principal(ATOR, request.app.state.config.memoria_namespaces)


Mem = Annotated[ServicoMemoria, Depends(_memoria)]
Pr = Annotated[Principal, Depends(_principal)]


@rm.post("/memorias", status_code=201)
def criar(d: MemoriaIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.criar(p, d, ATOR)


@rm.get("/memorias/buscar")
def buscar(
    s: Mem, p: Pr, q: Annotated[str, Query(min_length=1, max_length=300)],
    namespace: Annotated[list[str] | None, Query(max_length=10)] = None,
    fonte: Annotated[list[Literal["memoria", "codigo"]] | None, Query(max_length=2)] = None,
    tipo: Annotated[list[TipoMemoria] | None, Query(max_length=6)] = None,
    limite: Annotated[int, Query(ge=1, le=50)] = 10,
    apenas_validadas: bool = False,
    incluir_inativas: bool = False,
) -> dict[str, Any]:
    return s.buscar(p, q, namespace or ["publico"], tuple(fonte or ("memoria", "codigo")),
                    [x.value for x in tipo] if tipo else None, limite,
                    apenas_validadas, incluir_inativas)


@rm.post("/memorias/resolver-conflito")
def resolver_conflito(d: ResolverConflitoIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.resolver_conflito(p, d, ATOR)


@rm.post("/memorias/ingerir")
def ingerir(d: IngerirIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.ingerir_diretorio(p, d)


@rm.get("/memorias/estatisticas")
def estatisticas(s: Mem, p: Pr) -> dict[str, Any]:
    return s.estatisticas(p)


@rm.get("/memorias/{id_}")
def obter(id_: ID, s: Mem, p: Pr) -> dict[str, Any]:
    return s.obter(p, id_)


@rm.patch("/memorias/{id_}")
def atualizar(id_: ID, d: MemoriaAtualizaIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.atualizar(p, id_, d, ATOR)


@rm.post("/memorias/{id_}/transicao")
def transicionar(id_: ID, d: TransicaoMemoriaIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.transicionar(p, id_, d, ATOR)


@rm.post("/memorias/{id_}/evidencias")
def vincular(id_: ID, d: VincularEvidenciaIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.vincular_evidencia(p, id_, d.evidencia_id, ATOR)


@rm.post("/memorias/{id_}/validar")
def validar(id_: ID, d: ValidarIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.validar(p, id_, d, ATOR)


@rm.post("/memorias/{id_}/revalidar")
def revalidar(id_: ID, d: RevalidarIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.revalidar(p, id_, d, ATOR)


@rm.delete("/memorias/{id_}", status_code=204)
def remover(id_: ID, s: Mem, p: Pr) -> Response:
    s.remover(p, id_, ATOR)
    return Response(status_code=204)


@rm.post("/conhecimento/nos", status_code=201)
def criar_no(d: NoIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.criar_no(p, d, ATOR)


@rm.post("/conhecimento/arestas", status_code=201)
def criar_aresta(d: ArestaIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.criar_aresta(p, d, ATOR)


@rm.get("/conhecimento/nos/{id_}/vizinhos")
def vizinhos(id_: ID, s: Mem, p: Pr, saltos: Annotated[int, Query(ge=1, le=2)] = 1,
             tipo: Annotated[list[str] | None, Query(max_length=15)] = None) -> dict[str, Any]:
    return s.vizinhos(p, id_, saltos, tipo)
