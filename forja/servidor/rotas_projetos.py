"""Rotas de pastas de projeto, explorador de arquivos e anexos de tarefa. So traducao HTTP <-> ProjetosServico."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from forja.orquestracao.projetos_servico import MAX_BYTES_ANEXO, MAX_PASTAS, ProjetosServico
from forja.servidor.rotas import ATOR, ID, autenticar

rj = APIRouter(prefix="/api/v1", dependencies=[Depends(autenticar)])
Rel = Annotated[str, Field(max_length=500)]


class PastaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caminho: Annotated[str, Field(min_length=3, max_length=500)]
    papel: Literal["trabalho", "consulta"]


class PastasIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    pastas: list[PastaIn] = Field(max_length=MAX_PASTAS)


class AnexoProjetoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raiz: int = Field(ge=0, le=MAX_PASTAS)
    rel: Annotated[str, Field(min_length=1, max_length=500)]


class AnexoEnvioIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: Annotated[str, Field(min_length=1, max_length=200)]
    conteudo_b64: Annotated[str, Field(min_length=1, max_length=(MAX_BYTES_ANEXO * 4) // 3 + 8)]
    mime: Annotated[str, Field(max_length=100)] = ""


def _svc(request: Request) -> ProjetosServico:
    return request.app.state.projetos


Svc = Annotated[ProjetosServico, Depends(_svc)]


@rj.put("/projetos/{id_}/pastas")
def definir_pastas(id_: ID, d: PastasIn, s: Svc) -> dict[str, Any]:
    return s.definir_pastas(id_, [p.model_dump() for p in d.pastas], d.expected_version, ATOR)


@rj.get("/projetos/{id_}/arquivos")
def arquivos(id_: ID, s: Svc, raiz: Annotated[int, Query(ge=0, le=MAX_PASTAS)] = 0, rel: Annotated[str, Query(max_length=500)] = "") -> dict[str, Any]:
    return s.listar(id_, raiz, rel)


@rj.get("/projetos/{id_}/buscar-arquivos")
def buscar_arquivos(id_: ID, s: Svc, q: Annotated[str, Query(min_length=1, max_length=100)], limite: Annotated[int, Query(ge=1, le=50)] = 20) -> list[dict[str, Any]]:
    return s.buscar_arquivos(id_, q, limite)


@rj.get("/tarefas/{id_}/anexos")
def anexos(id_: ID, s: Svc) -> list[dict[str, Any]]:
    return s.anexos(id_)


@rj.post("/tarefas/{id_}/anexos/projeto", status_code=201)
def anexar_projeto(id_: ID, d: AnexoProjetoIn, s: Svc) -> dict[str, Any]:
    return s.anexar_do_projeto(id_, d.raiz, d.rel)


@rj.post("/tarefas/{id_}/anexos/envio", status_code=201)
def anexar_envio(id_: ID, d: AnexoEnvioIn, s: Svc) -> dict[str, Any]:
    return s.anexar_envio(id_, d.nome, d.conteudo_b64, d.mime)


@rj.delete("/tarefas/{id_}/anexos/{anexo_id}", status_code=204)
def remover_anexo(id_: ID, anexo_id: ID, s: Svc) -> Response:
    s.remover_anexo(id_, anexo_id)
    return Response(status_code=204)
