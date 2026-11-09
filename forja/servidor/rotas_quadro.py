"""Rotas do quadro de comunicacao e do painel de controle. Apenas traducao HTTP <-> QuadroServico."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from forja.dominio.quadro import MensagemIn, ResolverIn, TipoMensagem
from forja.orquestracao.quadro_servico import QuadroServico
from forja.servidor.rotas import ATOR, ID, autenticar

rq = APIRouter(prefix="/api/v1", dependencies=[Depends(autenticar)])


def _quadro(request: Request) -> QuadroServico:
    return request.app.state.quadro


Quadro = Annotated[QuadroServico, Depends(_quadro)]
DestinoQ = Annotated[str, Query(pattern=r"^(master|operador|todos|agente:[a-z0-9_.-]{1,40})$")]


@rq.post("/quadro")
def publicar(d: MensagemIn, q: Quadro, resposta: Response) -> dict[str, Any]:
    msg, criada = q.publicar(d, ATOR)
    resposta.status_code = 201 if criada else 200  # reenvio idempotente nao e erro
    return msg


@rq.get("/quadro")
def listar(
    q: Quadro,
    destino: DestinoQ | None = None,
    estado: Literal["pendente", "entregue", "resolvida", "expirada"] | None = None,
    tipo: TipoMensagem | None = None,
    prioridade_max: Annotated[int | None, Query(ge=1, le=5)] = None,
    limite: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    return q.listar(destino, estado, tipo.value if tipo else None, prioridade_max, limite)


@rq.post("/quadro/retirar")
def retirar(q: Quadro, destino: DestinoQ, limite: Annotated[int, Query(ge=1, le=50)] = 10) -> list[dict[str, Any]]:
    return q.retirar(destino, limite)


@rq.post("/quadro/{mensagem_id}/resolver")
def resolver(mensagem_id: ID, d: ResolverIn, q: Quadro) -> dict[str, Any]:
    return q.resolver(mensagem_id, ATOR, d.nota)


@rq.get("/controle/painel")
def painel_controle(q: Quadro) -> dict[str, Any]:
    return q.painel_controle()
