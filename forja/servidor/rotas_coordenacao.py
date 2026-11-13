"""Rotas do master/sub-masters, do caderno da tarefa (contexto fora da janela), dos relatos de status e dos agentes (Kiro/Codex).
Apenas traducao HTTP <-> servicos (limites e protecoes vivem nos servicos)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from forja.adapters.sqlite import tabelas as T
from forja.dominio.erros import NaoEncontrado
from forja.orquestracao.status import linha_do_tempo
from forja.servidor.rotas import ATOR, ID, autenticar

rc = APIRouter(prefix="/api/v1", dependencies=[Depends(autenticar)])
TipoCaderno = Literal["resolvido", "decisao", "arquivo", "erro", "pendencia", "fato"]


class CadernoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: TipoCaderno
    texto: str = Field(min_length=1, max_length=600)
    ref: str = Field("", max_length=200)


class FalaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texto: str = Field(min_length=1, max_length=8000)
    coordenacao_id: str | None = Field(None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


# ------------------------------------------------------------------ caderno da tarefa (usado pelo MCP do agente)
@rc.get("/tarefas/{id_}/caderno")
def caderno(id_: ID, request: Request, q: Annotated[str, Query(max_length=100)] = "",
            tipo: TipoCaderno | None = None) -> list[dict[str, Any]]:
    request.app.state.servico.obter(T.Tarefa, id_)  # 404 se a tarefa nao existe
    return request.app.state.caderno.listar(id_, q, tipo or "")


@rc.post("/tarefas/{id_}/caderno")
def caderno_salvar(id_: ID, d: CadernoIn, request: Request) -> dict[str, Any]:
    return request.app.state.caderno.salvar(id_, d.tipo, d.texto, d.ref, origem="agente")


# ------------------------------------------------------------------ status legivel (sem LLM, tempo real)
@rc.get("/execucoes/{id_}/status")
def status_execucao(id_: ID, request: Request) -> dict[str, Any]:
    r = linha_do_tempo(request.app.state.servico.repo, id_)
    if not r:
        raise NaoEncontrado(f"Execucao {id_} nao encontrada.")
    return r


# ------------------------------------------------------------------ master e sub-masters
@rc.get("/master")
def master(request: Request) -> dict[str, Any]:
    return request.app.state.coordenacao.painel()


@rc.post("/master/conversa")
def master_falar(d: FalaIn, request: Request) -> dict[str, Any]:
    return request.app.state.coordenacao.falar(d.texto, d.coordenacao_id, ATOR)


@rc.get("/coordenacoes/{id_}")
def coordenacao(id_: ID, request: Request) -> dict[str, Any]:
    c = request.app.state.coordenacao
    return {**c.obter(id_), "conversa": c.conversa(id_)}


@rc.post("/coordenacoes/{id_}/encerrar")
def coordenacao_encerrar(id_: ID, request: Request) -> dict[str, Any]:
    return request.app.state.coordenacao.encerrar(id_)


# ------------------------------------------------------------------ agentes disponiveis (Kiro e, se ligado, Codex)
@rc.get("/provedores")
def provedores(request: Request) -> dict[str, Any]:
    prov = request.app.state.servico.provedor
    if hasattr(prov, "estado"):
        return prov.estado()
    return {"modo": "so_kiro", "agentes": [{"id": prov.id, "configurado": True, "ativo": True, "resfriando_s": 0,
                                            "simulado": bool(getattr(prov, "mock", False))}]}
