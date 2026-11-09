"""Rotas do catalogo de ferramentas N0. Apenas traducao HTTP <-> Catalogo; regras vivem em `forja.ferramentas`."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from forja.ferramentas.catalogo import Catalogo
from forja.servidor.rotas import autenticar

rf = APIRouter(prefix="/api/v1", dependencies=[Depends(autenticar)])


def _catalogo(request: Request) -> Catalogo:
    return request.app.state.ferramentas


Cat = Annotated[Catalogo, Depends(_catalogo)]


class ExecutarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entrada: dict[str, Any] = {}


@rf.get("/ferramentas")
def listar(c: Cat) -> list[dict[str, Any]]:
    return c.listar()


@rf.get("/ferramentas/estatisticas")
def estatisticas(c: Cat) -> dict[str, dict[str, Any]]:
    return c.estatisticas()


@rf.post("/ferramentas/{ferramenta_id}/executar")
def executar(ferramenta_id: str, d: ExecutarIn, c: Cat) -> dict[str, Any]:
    return c.executar(ferramenta_id, d.entrada)
