"""Rotas do menu de configuracoes: preferencias do usuario e transparencia sobre onde ficam os dados. So traducao HTTP."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from forja.preferencias.servico import PreferenciasServico
from forja.servidor.rotas import autenticar
from forja.usuario.layout import SUBPASTAS, ignorado_pelo_git, raiz_do_repositorio

rp = APIRouter(prefix="/api/v1", dependencies=[Depends(autenticar)])


class AtualizarPreferenciasIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    valores: dict[str, Any] = Field(min_length=1, max_length=40)


class RestaurarPreferenciasIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    ids: list[str] = Field(min_length=1, max_length=40)


def _prefs(request: Request) -> PreferenciasServico:
    return request.app.state.prefs


Prefs = Annotated[PreferenciasServico, Depends(_prefs)]


@rp.get("/preferencias")
def listar(p: Prefs) -> dict[str, Any]:
    return p.estado()


@rp.put("/preferencias")
def atualizar(d: AtualizarPreferenciasIn, p: Prefs) -> dict[str, Any]:
    return p.atualizar(d.valores, d.expected_version)


@rp.post("/preferencias/restaurar")
def restaurar(d: RestaurarPreferenciasIn, p: Prefs) -> dict[str, Any]:
    return p.restaurar(d.ids, d.expected_version)


@rp.get("/usuario/perfil")
def perfil(request: Request) -> dict[str, Any]:
    """Onde ficam os dados do usuario e se estao protegidos do Git. Mostrado so ao operador autenticado, localmente."""
    pf = request.app.state.perfil
    repo = raiz_do_repositorio()
    dentro = False
    if repo is not None:
        try:
            pf.raiz.resolve().relative_to(repo.resolve())
            dentro = True
        except ValueError:
            dentro = False
    return {**pf.resumo(), "subpastas": list(SUBPASTAS), "dentro_do_repositorio": dentro,
            "ignorado_pelo_git": (ignorado_pelo_git(pf.raiz.resolve() / "forja.sqlite3", repo) if dentro and repo else None),
            "sobe_ao_git": ["codigo e logica", "configuracao padrao", "conhecimento publico pre-criado (knowledge/)", "testes e documentacao"],
            "fica_so_aqui": ["credenciais e tokens", "integracoes configuradas", "memoria e segundo cerebro", "notas e ferramentas extras",
                             "preferencias e permissoes", "tarefas, artefatos e logs"]}
