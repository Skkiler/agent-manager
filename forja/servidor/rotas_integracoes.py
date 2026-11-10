"""Rotas de integracoes: registro, configuracao pela tela (sem segredos) e teste de conexao. So traducao HTTP."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from forja.integracoes.registro import listar as listar_registro
from forja.orquestracao.acoes_externas import AcoesExternasServico
from forja.orquestracao.integracao_servico import IntegracaoServico
from forja.servidor.rotas import ATOR, autenticar

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


# ------------------------------------------------------------------ acoes externas (escrita com aprovacao por acao)
class ProporAcaoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    integracao: Idc
    acao: Annotated[str, Field(pattern=r"^[a-z][a-z_]{1,40}$")]
    parametros: dict[str, Any] = Field(default_factory=dict)
    dedup_key: Annotated[str, Field(min_length=1, max_length=100)] | None = None


class DecidirAcaoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aprovar: bool
    expected_version: int = Field(ge=1)
    adendo: Annotated[str, Field(max_length=1000)] = ""


def _acoes(request: Request) -> AcoesExternasServico:
    return request.app.state.acoes_externas


Acoes = Annotated[AcoesExternasServico, Depends(_acoes)]


@ri.get("/acoes-externas")
def listar_acoes(a: Acoes, estado: str | None = None) -> list[dict[str, Any]]:
    return a.listar(estado)


@ri.post("/acoes-externas", status_code=201)
def propor_acao(d: ProporAcaoIn, a: Acoes) -> dict[str, Any]:
    return a.propor(d.integracao, d.acao, d.parametros, solicitado_por=ATOR, dedup_key=d.dedup_key)[0]


@ri.post("/acoes-externas/{id_}/decidir")
def decidir_acao(id_: Annotated[str, Field(max_length=64)], d: DecidirAcaoIn, a: Acoes) -> dict[str, Any]:
    return a.decidir(id_, d.aprovar, d.expected_version, ATOR, d.adendo)
