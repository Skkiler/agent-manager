"""Login do painel por usuario e senha. Rotas publicas (sem token), com protecoes no servico (ContasServico).

- GET  /auth/estado      : o painel decide entre "primeiro acesso", "entrar" ou "ja conectado".
- POST /auth/configurar  : cria a PRIMEIRA conta; so do proprio computador (loopback) ou com o token da API.
- POST /auth/entrar      : usuario + senha -> token de sessao (guardado so nesta aba do navegador).
- POST /auth/sair        : revoga a sessao.
- POST /auth/senha       : troca a senha (exige a atual); derruba as outras sessoes.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from forja.dominio.erros import CredenciaisInvalidas
from forja.seguranca.auth import extrair_bearer, token_confere

ra = APIRouter(prefix="/api/v1/auth")
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
Nome = Annotated[str, Field(min_length=1, max_length=64)]
Senha = Annotated[str, Field(min_length=1, max_length=200)]


class EntrarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    usuario: Nome
    senha: Senha


class TrocarSenhaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    senha_atual: Senha
    nova_senha: Senha


def _contas(request: Request) -> Any:
    return request.app.state.contas


def _bearer(request: Request) -> str | None:
    return extrair_bearer(request.headers.get("authorization"))


def _endereco(request: Request) -> str:
    return request.client.host if request.client else "desconhecido"


def _pode_configurar(request: Request) -> bool:
    """Primeiro acesso: quem esta no proprio computador, ou quem provar acesso ao token da API (arquivo local)."""
    esperado = request.app.state.token
    return _endereco(request) in LOOPBACK or (esperado is not None and token_confere(_bearer(request), esperado))


@ra.get("/estado")
def estado(request: Request) -> dict[str, Any]:
    exige = request.app.state.token is not None
    contas = _contas(request)
    existe = contas.existe_conta()
    sessao = contas.sessao(_bearer(request)) if exige else None
    api_token = exige and token_confere(_bearer(request), request.app.state.token)
    return {"exige_login": exige, "configurado": existe, "pode_configurar": exige and not existe and _pode_configurar(request),
            "conectado": (not exige) or sessao is not None or api_token,
            "usuario": (sessao or {}).get("usuario") or ("token da API" if api_token else None)}


@ra.post("/configurar", status_code=201)
def configurar(d: EntrarIn, request: Request) -> dict[str, Any]:
    if not _pode_configurar(request):
        raise CredenciaisInvalidas("O primeiro acesso só pode ser configurado no próprio computador do servidor "
                                   "(ou com o token da API). Veja o README.")
    return _contas(request).configurar_primeira(d.usuario, d.senha)


@ra.post("/entrar")
def entrar(d: EntrarIn, request: Request) -> dict[str, Any]:
    return _contas(request).entrar(d.usuario, d.senha, _endereco(request))


@ra.post("/sair", status_code=204)
def sair(request: Request) -> Response:
    _contas(request).sair(_bearer(request))
    return Response(status_code=204)


@ra.post("/senha")
def trocar_senha(d: TrocarSenhaIn, request: Request) -> dict[str, Any]:
    return _contas(request).trocar_senha(_bearer(request) or "", d.senha_atual, d.nova_senha)
