"""Rotas do sistema: configuracao (modelo por parte, nivel de detalhe), integracoes e revisao do esquema."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response

from forja.dominio.configuracao import SalvarConfiguracaoIn
from forja.dominio.revisao import SolicitarRevisaoIn
from forja.orquestracao.configuracao_servico import ConfiguracaoServico
from forja.orquestracao.estudos import EstudoIn
from forja.orquestracao.revisao import RevisaoServico
from forja.servidor.rotas import autenticar

rs = APIRouter(prefix="/api/v1", dependencies=[Depends(autenticar)])


def _config(request: Request) -> ConfiguracaoServico:
    return request.app.state.configuracao


def _revisao(request: Request) -> RevisaoServico:
    return request.app.state.revisao


Cfg = Annotated[ConfiguracaoServico, Depends(_config)]


@rs.get("/configuracao")
def obter_configuracao(c: Cfg) -> dict[str, Any]:
    return c.obter()


@rs.get("/configuracao/modelos")
def modelos_da_conta(request: Request) -> dict[str, Any]:
    """Modelos aceitos pela conta Kiro com o custo relativo em creditos (consulta somente leitura, em cache)."""
    return request.app.state.modelos.listar()


@rs.put("/configuracao")
def salvar_configuracao(d: SalvarConfiguracaoIn, c: Cfg) -> dict[str, Any]:
    return c.salvar(d)


@rs.post("/revisoes", status_code=201)
def solicitar_revisao(d: SolicitarRevisaoIn, r: Annotated[RevisaoServico, Depends(_revisao)],
                      resposta: Response) -> dict[str, Any]:
    resposta.headers["Cache-Control"] = "no-store"
    return r.solicitar(list(d.escopo), d.pesquisar_web, d.executar)


@rs.post("/estudos", status_code=201)
def solicitar_estudo(d: EstudoIn, request: Request, resposta: Response) -> dict[str, Any]:
    """Pede a um agente de estudo para analisar uma PASTA (permitida) ou pesquisar um TOPICO e alimentar o segundo cerebro.
    Cria uma tarefa preparada (executa so com `executar=true`, pois consome creditos). As notas nascem candidatas."""
    resposta.headers["Cache-Control"] = "no-store"
    return request.app.state.estudos.solicitar(d)
