"""Rotas de integracoes: registro, configuracao pela tela (sem segredos) e teste de conexao. So traducao HTTP."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from forja.integracoes.registro import listar as listar_registro
from forja.orquestracao.integracao_servico import IntegracaoServico
from forja.servidor.rotas import autenticar

ri = APIRouter(prefix="/api/v1", dependencies=[Depends(autenticar)])
Idc = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")]


class SalvarIntegracaoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    configuracao: dict[str, Any]


def _svc(request: Request) -> IntegracaoServico:
    return request.app.state.integracoes


Svc = Annotated[IntegracaoServico, Depends(_svc)]


@ri.get("/integracoes")
def integracoes(request: Request, s: Svc) -> list[dict[str, Any]]:
    from forja.integracoes.conectores import CONECTORES

    estados = {i: s.estado(i) for i in CONECTORES}
    prontas = {i for i, e in estados.items() if e["pronta"]}
    saida = listar_registro(set(request.app.state.ferramentas.ferramentas), prontas)
    for item in saida:
        item["rede_estado"] = estados.get(item["id"])  # None para locais e planejados
    return saida


@ri.get("/integracoes/{id_}")
def integracao(id_: Idc, s: Svc) -> dict[str, Any]:
    return s.estado(id_)


@ri.put("/integracoes/{id_}/configuracao")
def salvar(id_: Idc, d: SalvarIntegracaoIn, s: Svc) -> dict[str, Any]:
    return s.salvar(id_, d.configuracao, d.expected_version)


@ri.post("/integracoes/{id_}/testar")
def testar(id_: Idc, s: Svc) -> dict[str, Any]:
    return s.testar(id_)
