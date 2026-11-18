"""Rotas da area de trabalho do painel (editor, Git, terminal, Docker, problemas, busca). So traducao HTTP <-> AreaTrabalho."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from forja.orquestracao.area_trabalho import AreaTrabalho
from forja.orquestracao.projetos_servico import MAX_PASTAS
from forja.servidor.rotas import autenticar

ra2 = APIRouter(prefix="/api/v1/area", dependencies=[Depends(autenticar)])
Rel = Annotated[str, Field(min_length=1, max_length=500)]
Raiz = Annotated[int, Field(ge=0, le=MAX_PASTAS)]


def _svc(request: Request) -> AreaTrabalho:
    return request.app.state.area


Svc = Annotated[AreaTrabalho, Depends(_svc)]
QRaiz = Annotated[int, Query(ge=0, le=MAX_PASTAS)]
QID = Annotated[str, Query(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
QRel = Annotated[str, Query(min_length=1, max_length=500)]


class SalvarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projeto: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
    raiz: Raiz
    rel: Rel
    conteudo: Annotated[str, Field(max_length=2_000_000)]
    sha: Annotated[str, Field(max_length=64)] | None = None


class ProblemasIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projeto: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
    raiz: Raiz
    rel: Rel
    conteudo: Annotated[str, Field(max_length=2_000_000)] | None = None


class GitAcaoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projeto: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
    raiz: Raiz
    acao: Literal["stage", "unstage", "commit"]
    arquivos: list[Annotated[str, Field(max_length=500)]] = Field(default_factory=list, max_length=200)
    mensagem: Annotated[str, Field(max_length=2000)] = ""


class TerminalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projeto: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
    raiz: Raiz
    comando: Annotated[str, Field(min_length=1, max_length=2000)]


class DockerAcaoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Annotated[str, Field(min_length=1, max_length=128)]
    acao: Literal["start", "stop", "restart"]


@ra2.get("/arquivo")
def ler(s: Svc, projeto: QID, rel: QRel, raiz: QRaiz = 0) -> dict[str, Any]:
    return s.ler(projeto, raiz, rel)


@ra2.put("/arquivo")
def salvar(d: SalvarIn, s: Svc) -> dict[str, Any]:
    return s.salvar(d.projeto, d.raiz, d.rel, d.conteudo, d.sha)


@ra2.post("/problemas")
def problemas(d: ProblemasIn, s: Svc) -> dict[str, Any]:
    return s.problemas(d.projeto, d.raiz, d.rel, d.conteudo)


@ra2.get("/buscar")
def buscar(s: Svc, projeto: QID, padrao: Annotated[str, Query(min_length=1, max_length=200)], raiz: QRaiz = 0, regex: bool = False,
           incluir: Annotated[str, Query(max_length=60, pattern=r"^[A-Za-z0-9_.*?\-\[\]]*$")] = "") -> dict[str, Any]:
    return s.buscar(projeto, raiz, padrao, regex, incluir)


@ra2.get("/git")
def git(s: Svc, projeto: QID, raiz: QRaiz = 0,
        operacao: Annotated[str, Query(pattern=r"^(status|log|diff|blame|show|branches)$")] = "status",
        ref: Annotated[str, Query(max_length=120)] = "", arquivo: Annotated[str, Query(max_length=500)] = "",
        limite: Annotated[int, Query(ge=1, le=100)] = 30) -> dict[str, Any]:
    return s.git(projeto, raiz, operacao, ref, arquivo, limite)


@ra2.post("/git")
def git_acao(d: GitAcaoIn, s: Svc) -> dict[str, Any]:
    return s.git_acao(d.projeto, d.raiz, d.acao, d.arquivos, d.mensagem)


@ra2.post("/terminal")
def terminal(d: TerminalIn, s: Svc) -> dict[str, Any]:
    return s.terminal(d.projeto, d.raiz, d.comando)


@ra2.get("/docker")
def docker(s: Svc, recurso: Annotated[str, Query(pattern=r"^(containers|imagens|compose)$")] = "containers") -> list[dict[str, Any]]:
    return s.docker(recurso)


@ra2.get("/docker/logs")
def docker_logs(s: Svc, id: Annotated[str, Query(min_length=1, max_length=128)], linhas: Annotated[int, Query(ge=1, le=2000)] = 200) -> dict[str, Any]:  # noqa: A002
    return s.docker_logs(id, linhas)


@ra2.post("/docker")
def docker_acao(d: DockerAcaoIn, s: Svc) -> dict[str, Any]:
    return s.docker_acao(d.id, d.acao)
