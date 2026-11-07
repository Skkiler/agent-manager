"""Fabrica da aplicacao FastAPI. Monta dependencias, middleware de seguranca e ciclo de vida."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp, montar_comando, resolver_cli
from forja.adapters.sqlite.banco import criar_engines, migrar
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.agentes.base import ProvedorAgente
from forja.config import Configuracoes, obter_configuracoes
from forja.dominio.erros import ErroDominio
from forja.observabilidade.logs import configurar_logging, correlation_id_var
from forja.orquestracao.servico import Servico
from forja.seguranca.auth import LimitadorTaxa, carregar_token
from forja.servidor.rotas import publico, r

log = logging.getLogger("forja.app")
ESTATICO = __import__("pathlib").Path(__file__).resolve().parent.parent / "painel" / "estatico"


def criar_provedor_kiro(cfg: Configuracoes) -> ProvedorKiroAcp:
    cli = resolver_cli(cfg.app_kiro_cli_path)
    comando = montar_comando(cli, cfg.app_kiro_agent, cfg.app_kiro_model) if cli else None
    if comando is None:
        log.warning("Kiro CLI nao encontrado; execucoes ficarao bloqueadas (kiro_cli_ausente)")
    return ProvedorKiroAcp(comando, cfg.kiro_workspace_dir, float(cfg.app_kiro_prompt_timeout_seconds))


def criar_servico(cfg: Configuracoes, provedor: ProvedorAgente | None = None) -> Servico:
    migrar(cfg.db_path)
    cfg.artefatos_dir.mkdir(parents=True, exist_ok=True)
    engine_w, engine_r = criar_engines(cfg.db_path)
    repo = RepositorioSqlite(engine_w, engine_r)
    perfil_workers = 1 if cfg.app_resource_profile == "essencial" else cfg.app_max_parallel_cpu_tools
    if provedor is None and cfg.app_kiro_acp_enabled:
        provedor = criar_provedor_kiro(cfg)
    return Servico(repo, provedor or AgenteMock(), cfg.artefatos_dir, max_workers=perfil_workers,
                   lock_lease_seconds=cfg.app_lock_lease_seconds)


def criar_app(cfg: Configuracoes | None = None, provedor: ProvedorAgente | None = None) -> FastAPI:
    cfg = cfg or obter_configuracoes()
    configurar_logging(cfg.app_log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.servico.recuperar()
        log.info("servidor pronto", extra={"evento": "servidor.pronto"})
        try:
            yield
        finally:
            app.state.encerrando.set()
            app.state.servico.encerrar()

    app = FastAPI(title="Forja", version=__import__("forja").__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.config = cfg
    app.state.servico = provedor_servico = criar_servico(cfg, provedor)
    app.state.token = carregar_token(cfg)
    app.state.limitador = LimitadorTaxa(cfg.app_rate_limit_per_minute)
    app.state.encerrando = threading.Event()
    app.state.hosts = {"127.0.0.1", "localhost", "::1", f"127.0.0.1:{cfg.app_port}", f"localhost:{cfg.app_port}"}
    app.state.hosts |= {h.strip() for h in cfg.app_allowed_hosts.split(",") if h.strip()}

    _registrar_middleware(app, cfg)
    _registrar_handlers(app)
    app.include_router(publico)
    app.include_router(r)
    _ = provedor_servico  # servico ja referenciado em app.state

    if ESTATICO.exists():
        app.mount("/estatico", StaticFiles(directory=ESTATICO), name="estatico")

        @app.get("/", include_in_schema=False)
        def raiz() -> FileResponse:
            return FileResponse(ESTATICO / "index.html")

    return app


def _registrar_middleware(app: FastAPI, cfg: Configuracoes) -> None:
    @app.middleware("http")
    async def seguranca(request: Request, call_next):  # noqa: ANN001
        token = correlation_id_var.set(request.headers.get("X-Correlation-ID") or uuid.uuid4().hex)
        try:
            host = (request.headers.get("host") or "").lower()
            if host and host not in app.state.hosts:
                return JSONResponse(status_code=400,
                                    content={"erro": "host_nao_permitido", "mensagem": "Host invalido."})
            origem = request.headers.get("origin")
            if request.method not in ("GET", "HEAD", "OPTIONS") and origem is not None:
                host_origem = origem.split("://", 1)[-1].lower()
                if host_origem not in app.state.hosts:
                    return JSONResponse(status_code=403, content={"erro": "origem_rejeitada",
                                        "mensagem": "Origin nao permitida (protecao CSRF)."})
            cliente = request.client.host if request.client else "desconhecido"
            if not app.state.limitador.permitir(cliente):
                return JSONResponse(status_code=429, content={"erro": "rate_limit", "mensagem": "Muitas requisicoes."})
            resposta = await call_next(request)
            resposta.headers["X-Correlation-ID"] = correlation_id_var.get() or ""
            resposta.headers["X-Content-Type-Options"] = "nosniff"
            resposta.headers["Referrer-Policy"] = "no-referrer"
            return resposta
        finally:
            correlation_id_var.reset(token)


def _registrar_handlers(app: FastAPI) -> None:
    @app.exception_handler(ErroDominio)
    async def _dominio(request: Request, exc: ErroDominio):  # noqa: ANN202, ARG001
        return JSONResponse(status_code=exc.status, content={"erro": exc.codigo, "mensagem": exc.mensagem})

    @app.exception_handler(RequestValidationError)
    async def _validacao(request: Request, exc: RequestValidationError):  # noqa: ANN202, ARG001
        detalhes = [
            {"local": list(e.get("loc", [])), "tipo": e.get("type", ""), "msg": str(e.get("msg", ""))}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"erro": "validacao", "detalhes": detalhes})
