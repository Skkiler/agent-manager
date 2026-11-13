"""Fabrica da aplicacao FastAPI. Monta dependencias, middleware de seguranca e ciclo de vida."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from forja.adapters.agentes_mock.mock import AgenteMock
from forja.adapters.codex_acp.provedor import ProvedorCodexAcp, resolver_codex
from forja.adapters.kiro_acp import perfil_kiro
from forja.adapters.kiro_acp.modelos import CatalogoModelos
from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp, montar_comando, resolver_cli
from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.banco import criar_engines, migrar
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.agentes.base import ProvedorAgente
from forja.agentes.roteador import ProvedoresRoteados
from forja.config import Configuracoes, obter_configuracoes
from forja.contexto.construtor import ConstrutorContexto
from forja.dominio.erros import ErroDominio
from forja.ferramentas.catalogo import Catalogo
from forja.integracoes import ambiente
from forja.memoria.base import semear as semear_base
from forja.memoria.base import sincronizar_pacotes
from forja.memoria.modelo import Principal
from forja.memoria.rotulagem import RotulagemServico
from forja.observabilidade.logs import configurar_logging, correlation_id_var
from forja.observabilidade.telemetria import Telemetria
from forja.orquestracao.acoes_externas import AcoesExternasServico
from forja.orquestracao.aprendizado_rotas import AprendizadoRotas
from forja.orquestracao.caderno import Caderno
from forja.orquestracao.configuracao_servico import ConfiguracaoServico
from forja.orquestracao.contas_servico import ContasServico
from forja.orquestracao.coordenacao import CoordenacaoServico
from forja.orquestracao.custos import CustosServico
from forja.orquestracao.estudos import EstudoServico
from forja.orquestracao.grafo_servico import GrafoServico
from forja.orquestracao.integracao_servico import IntegracaoServico
from forja.orquestracao.isolamento import Isolamento
from forja.orquestracao.memoria_servico import ServicoMemoria
from forja.orquestracao.oficina import OficinaServico
from forja.orquestracao.organizacao import OrganizadorMemoria
from forja.orquestracao.projetos_servico import ProjetosServico
from forja.orquestracao.propostas import PropostasMemoria
from forja.orquestracao.quadro_servico import QuadroServico
from forja.orquestracao.restauracao import PontosRestauracao
from forja.orquestracao.revisao import RevisaoServico
from forja.orquestracao.servico import Servico
from forja.orquestracao.status import StatusServico
from forja.orquestracao.subtarefas import SubtarefasServico
from forja.orquestracao.visoes import VisaoKanban
from forja.preferencias.registro import POR_ID
from forja.preferencias.servico import PreferenciasServico
from forja.seguranca.auth import LimitadorTaxa, carregar_token
from forja.seguranca.pastas import definir_protegidas
from forja.servidor.rotas import publico, r
from forja.servidor.rotas_auth import ra
from forja.servidor.rotas_coordenacao import rc
from forja.servidor.rotas_ferramentas import rf
from forja.servidor.rotas_integracoes import ri
from forja.servidor.rotas_memoria import rm
from forja.servidor.rotas_orquestracao import rx
from forja.servidor.rotas_preferencias import rp
from forja.servidor.rotas_projetos import rj
from forja.servidor.rotas_quadro import rq
from forja.servidor.rotas_sistema import rs
from forja.servidor.rotas_visoes import rv
from forja.usuario.layout import validar_fora_do_git

log = logging.getLogger("forja.app")
ESTATICO = __import__("pathlib").Path(__file__).resolve().parent.parent / "painel" / "estatico"


def _mcp_forja(cfg: Configuracoes) -> list[dict]:
    """Descricao (stdio) do MCP da Forja entregue ao Kiro. Leva so enderecos e nomes de perfil: o token e lido pelo proprio MCP."""
    import sys

    env = {"FORJA_MCP_URL": f"http://127.0.0.1:{cfg.app_port}"}
    for nome, valor in (("APP_USER_HOME", cfg.app_user_home), ("APP_PROFILE", cfg.app_profile), ("APP_DATA_DIR", cfg.app_data_dir)):
        if valor:
            env[nome] = str(valor)
    return [{"name": "forja", "command": sys.executable, "args": ["-m", "forja.mcp"], "env": [{"name": k, "value": v} for k, v in env.items()]}]


def kiro_de(prov: Any) -> ProvedorKiroAcp | None:
    """O agente Kiro real (direto ou dentro do roteador de agentes). None = agente simulado (testes/demonstracao)."""
    if isinstance(prov, ProvedoresRoteados):
        return prov.kiro if isinstance(prov.kiro, ProvedorKiroAcp) else None
    return prov if isinstance(prov, ProvedorKiroAcp) else None


def agentes_reais(prov: Any) -> list[ProvedorKiroAcp]:
    """Kiro e Codex (quando existem): recebem os mesmos controles (orcamentos, escopo, contexto, autonomia)."""
    if isinstance(prov, ProvedoresRoteados):
        return [a for a in (prov.kiro, prov.codex) if isinstance(a, ProvedorKiroAcp)]
    return [prov] if isinstance(prov, ProvedorKiroAcp) else []


def criar_provedor_kiro(cfg: Configuracoes) -> ProvedorKiroAcp:
    cli = resolver_cli(cfg.app_kiro_cli_path)
    comando = montar_comando(cli, cfg.app_kiro_agent, cfg.app_kiro_model) if cli else None
    if comando is None:
        log.warning("Kiro CLI nao encontrado; execucoes ficarao bloqueadas (kiro_cli_ausente)")
    else:
        try:  # perfil com regras DENY para segredos; sem ele, execucoes em pastas de projeto ficam bloqueadas (falha fechada)
            perfil_kiro.garantir(protegidas=[cfg.dados_dir, cfg.credenciais_dir])
        except OSError as e:
            log.warning("nao foi possivel gravar o perfil do Kiro: %s", type(e).__name__)
    return ProvedorKiroAcp(comando, cfg.kiro_workspace_dir, float(cfg.app_kiro_prompt_timeout_seconds), mcp_servers=_mcp_forja(cfg))


def criar_servico(cfg: Configuracoes, provedor: ProvedorAgente | None = None) -> Servico:
    migrar(cfg.db_path)
    cfg.artefatos_dir.mkdir(parents=True, exist_ok=True)
    engine_w, engine_r = criar_engines(cfg.db_path)
    repo = RepositorioSqlite(engine_w, engine_r)
    perfil_workers = 1 if cfg.app_resource_profile == "essencial" else cfg.app_max_parallel_cpu_tools
    if provedor is None and cfg.app_kiro_acp_enabled:
        # Kiro (principal) + Codex (opcional, desligado ate voce ligar): mesma interface, contextos separados (agentes/roteador.py)
        codex = ProvedorCodexAcp(resolver_codex(cfg.app_codex_acp_command), cfg.kiro_workspace_dir / "codex", cfg.app_codex_model,
                                 timeout_prompt=float(cfg.app_kiro_prompt_timeout_seconds))
        provedor = ProvedoresRoteados(criar_provedor_kiro(cfg), codex)
    return Servico(repo, provedor or AgenteMock(), cfg.artefatos_dir, max_workers=perfil_workers,
                   espera_aprovacao_s=float(cfg.app_approval_timeout_seconds),
                   lock_lease_seconds=cfg.app_lock_lease_seconds)


def _criar_preferencias(cfg: Configuracoes, servico: Servico, app: FastAPI) -> PreferenciasServico:
    """Preferencias do usuario. Valores do ambiente (.env) valem como ponto de partida ate o usuario salvar na tela."""
    sementes: dict = {}
    if cfg.ferramentas_raizes:  # APP_TOOLS_ROOTS (legado): liga a leitura e permite essas pastas
        sementes.update(ferramentas_arquivos_ativas=True, pastas_permitidas=[str(p) for p in cfg.ferramentas_raizes])
    for pref, valor in (("limite_requisicoes_por_minuto", cfg.app_rate_limit_per_minute), ("aprovacao_timeout_segundos", cfg.app_approval_timeout_seconds),
                        ("contexto_orcamento_tokens", cfg.app_context_budget_tokens), ("contexto_ativo", cfg.app_context_enabled)):
        if valor != POR_ID[pref].padrao:
            sementes[pref] = valor
    prefs = PreferenciasServico(servico.repo, sementes=sementes)
    prov = kiro_de(servico.provedor)
    if prov is not None:
        prefs.registrar_aplicador("kiro_mcp_ativo", lambda v: setattr(prov, "usar_mcp", bool(v)))
        prefs.registrar_aplicador("kiro_mcp_ativo", lambda v: setattr(servico.construtor_contexto, "referencias", bool(v))
                                  if servico.construtor_contexto is not None else None)
        prefs.registrar_aplicador("kiro_reusar_sessao", lambda v: setattr(prov, "reusar_sessao", bool(v)))
        for ag in agentes_reais(servico.provedor):  # orcamentos e controles valem para TODOS os agentes (Kiro e Codex)
            prefs.registrar_aplicador("limite_ferramentas_por_execucao", lambda v, ag=ag: setattr(ag, "max_ferramentas", int(v)))
            prefs.registrar_aplicador("controle_escopo", lambda v, ag=ag: setattr(ag, "controle_escopo", str(v)))
            prefs.registrar_aplicador("contexto_limite_sessao", lambda v, ag=ag: (setattr(ag, "limite_contexto_sessao", int(v)),
                                                                                  setattr(ag, "limite_contexto_reuso", int(v))))
            prefs.registrar_aplicador("subagentes", lambda v, ag=ag: setattr(ag, "subagentes", str(v)))
    prefs.registrar_aplicador("contexto_ativo", lambda v: setattr(servico, "contexto_ativo", bool(v)))
    prefs.registrar_aplicador("aprovacao_timeout_segundos", lambda v: setattr(servico, "espera_aprovacao_s", float(v)))
    prefs.registrar_aplicador("contexto_orcamento_tokens", lambda v: setattr(servico.construtor_contexto, "orcamento", int(v))
                              if servico.construtor_contexto is not None else None)
    definir_protegidas([app.state.perfil.raiz])  # dados do usuario: nenhuma ferramenta le, com qualquer configuracao
    return prefs


def _melhorias_orquestrador(app: FastAPI, cfg: Configuracoes, servico: Servico) -> None:
    """Desfazer por tarefa, pastas isoladas, telemetria, roteamento aprendido, subagentes, custo, oficina e organizacao do
    segundo cerebro. Cada peca e opcional e de melhor esforco: falhar nela nunca altera o resultado de uma execucao."""
    prefs, repo, prov = app.state.prefs, servico.repo, servico.provedor
    servico.restauracao = app.state.restauracao = PontosRestauracao(repo, cfg.artefatos_dir.parent / "pontos")
    servico.isolamento = app.state.isolamento = Isolamento(repo)
    app.state.kanban.restauracao = app.state.restauracao
    app.state.telemetria = Telemetria(repo, cfg.logs_dir, cfg.app_otel_endpoint)
    app.state.aprendizado = AprendizadoRotas(repo)
    app.state.subtarefas = SubtarefasServico(servico)
    app.state.custos = CustosServico(repo, app.state.modelos)
    kiro = kiro_de(prov)
    app.state.oficina = OficinaServico(repo, (lambda: kiro.max_ferramentas) if kiro is not None else None)
    app.state.organizador = OrganizadorMemoria(repo, app.state.memoria, app.state.grafo, Principal("organizacao", cfg.memoria_namespaces))
    app.state.organizador.resumir = app.state.estudos.solicitar_resumo  # topicos resumidos pelo Kiro (parte 'estudo')
    # contexto fora da janela (caderno + ficha de estado), relatos de status baratos e coordenacao (master/sub-masters)
    app.state.caderno = Caderno(repo)
    app.state.status = StatusServico(repo, getattr(prov, "turno_rapido", None) if kiro is not None else None)
    app.state.coordenacao = CoordenacaoServico(servico, prefs.perfil_trabalho)
    app.state.status.publicar.append(app.state.coordenacao.publicar_status)
    servico.ao_finalizar += [app.state.telemetria.ao_finalizar, app.state.aprendizado.ao_finalizar, app.state.subtarefas.ao_finalizar,
                             app.state.coordenacao.ao_finalizar, app.state.status.ao_finalizar]
    for ag in agentes_reais(prov):
        ag.ajustar_rota = app.state.aprendizado.ajustar
        ag.ficha_de = lambda tarefa: _ficha(repo, app.state.caderno, tarefa)
    servico.controle_escopo = "pausar"
    prefs.registrar_aplicador("controle_escopo", lambda v: setattr(servico, "controle_escopo", str(v)))
    prefs.registrar_aplicador("status_resumos", lambda v: setattr(app.state.status, "modo", str(v)))
    prefs.registrar_aplicador("master_executar", lambda v: setattr(app.state.coordenacao, "executar", str(v) == "executar"))
    if isinstance(prov, ProvedoresRoteados):
        prefs.registrar_aplicador("codex_ativo", lambda v: setattr(prov, "codex_ativo", bool(v)))
        prefs.registrar_aplicador("distribuicao_provedores", lambda v: setattr(prov, "modo", str(v)))
    prefs.registrar_aplicador("subagentes", lambda v: setattr(app.state.subtarefas, "modo", str(v)))
    prefs.registrar_aplicador("pontos_restauracao", lambda v: setattr(servico, "pontos_ativos", bool(v)))
    prefs.registrar_aplicador("isolar_paralelas", lambda v: setattr(servico.isolamento, "ativo", bool(v)))
    prefs.registrar_aplicador("roteamento_aprende", lambda v: setattr(app.state.aprendizado, "ativo", bool(v)))
    prefs.registrar_aplicador("retomar_apos_queda", lambda v: setattr(servico, "retomar_apos_queda", str(v)))
    prefs.registrar_aplicador("organizacao_memoria", lambda v: setattr(app.state.organizador, "modo", str(v)))
    prefs.registrar_aplicador("telemetria", app.state.telemetria.definir_modo)
    prefs.registrar_aplicador("pacotes_conhecimento", lambda v: _pacotes_conhecimento(repo, v))


def _ficha(repo: RepositorioSqlite, caderno: Caderno, tarefa: dict) -> str:
    """Ficha de estado da tarefa (caderno + o que a execucao aberta ja fez), para trocar de sessao sem perder o fio."""
    with repo.leitura() as t:
        execs = [e for e in t.listar(T.Execucao, tarefa_id=tarefa["id"], limite=50)]
        return caderno.ficha(t, tarefa, execs[-1]["id"] if execs else None)


def _pacotes_conhecimento(repo: RepositorioSqlite, escolhidos: list[str]) -> None:
    try:  # instala os marcados e remove os desmarcados (idempotente; so grava o que mudou)
        sincronizar_pacotes(repo, list(escolhidos or []))
    except Exception as e:  # noqa: BLE001 - pacote e conhecimento extra; falhar nao impede o servidor
        log.warning("nao foi possivel sincronizar os pacotes de conhecimento: %s", type(e).__name__)


def criar_app(cfg: Configuracoes | None = None, provedor: ProvedorAgente | None = None) -> FastAPI:
    cfg = cfg or obter_configuracoes()
    configurar_logging(cfg.app_log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.servico.recuperar()
        app.state.acoes_externas.recuperar()
        app.state.organizador.iniciar()  # organizacao do segundo cerebro em segundo plano (so sugere; preferencia)
        log.info("servidor pronto", extra={"evento": "servidor.pronto"})
        try:
            yield
        finally:
            app.state.encerrando.set()
            app.state.organizador.parar()
            app.state.servico.encerrar()

    app = FastAPI(title="Forja", version=__import__("forja").__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.config = cfg
    perfil = cfg.perfil_usuario()
    if cfg.app_data_dir is None:  # perfil real do usuario (nao e um diretorio explicito de teste)
        validar_fora_do_git(perfil)
        perfil.criar()
        if perfil.legado:
            log.warning("Dados do usuario em ./data (modo legado). Migre para fora do repositorio: python scripts/migrar_dados_usuario.py")
    ambiente.definir_arquivos([perfil.arquivo_env, Path(".env")])  # segredos de integracao: .env do usuario primeiro
    app.state.perfil = perfil
    app.state.servico = provedor_servico = criar_servico(cfg, provedor)
    _ = cfg.memoria_namespaces  # falha cedo se APP_MEMORY_ALLOWED_NAMESPACES for invalido
    app.state.memoria = ServicoMemoria(provedor_servico.repo, raizes_ingestao=cfg.memoria_raizes)
    try:  # base de conhecimento inicial (curada, versionada): idempotente, so grava o que mudou
        log.info("base de conhecimento da Forja", extra={"evento": "memoria.base", **semear_base(provedor_servico.repo)})
    except Exception as e:  # noqa: BLE001 - a base e conhecimento extra; falhar nao impede o servidor
        log.warning("nao foi possivel semear a base de conhecimento: %s", type(e).__name__)
    if cfg.app_context_enabled and cfg.contexto_namespaces:
        ns = cfg.contexto_namespaces
        provedor_servico.construtor_contexto = ConstrutorContexto(
            app.state.memoria, Principal("contexto", frozenset(ns)), ns, orcamento=cfg.app_context_budget_tokens)
    app.state.propostas = PropostasMemoria(provedor_servico, app.state.memoria)
    app.state.rotulagem = RotulagemServico(provedor_servico.repo, app.state.memoria)
    app.state.integracoes = IntegracaoServico(provedor_servico.repo)
    app.state.prefs = _criar_preferencias(cfg, provedor_servico, app)
    fixas = [r.resolve() for r in cfg.memoria_raizes]  # APP_MEMORY_INGEST_ROOTS continua valendo; a tela soma as pastas permitidas

    def _raizes_ingestao(_v: object = None) -> None:
        pol = app.state.prefs.politica_pastas()
        app.state.memoria.raizes = list(dict.fromkeys(fixas + ([p.resolve() for p in pol.permitidas] if pol.ativa else [])))

    for pref in ("ferramentas_arquivos_ativas", "pastas_permitidas"):
        app.state.prefs.registrar_aplicador(pref, _raizes_ingestao)
    _raizes_ingestao()
    app.state.projetos = provedor_servico.projetos = ProjetosServico(provedor_servico.repo, cfg.artefatos_dir, politica=app.state.prefs.politica_pastas)
    provedor_servico.perfil_de = app.state.prefs.perfil_trabalho  # autonomia/metodos/observacoes lidos a cada execucao
    for ag in agentes_reais(provedor_servico.provedor):
        ag.perfil_de = app.state.prefs.perfil_trabalho
    app.state.quadro = provedor_servico.quadro = QuadroServico(provedor_servico.repo)  # orquestrador avisa o quadro
    app.state.acoes_externas = AcoesExternasServico(provedor_servico.repo, app.state.integracoes, app.state.quadro)
    app.state.ferramentas = Catalogo((), app.state.integracoes, app.state.acoes_externas, politica=app.state.prefs.politica_pastas)
    app.state.kanban = VisaoKanban(provedor_servico.repo)
    app.state.grafo = GrafoServico(provedor_servico.repo)
    app.state.configuracao = ConfiguracaoServico(provedor_servico.repo, modelo_padrao=cfg.app_kiro_model)
    app.state.revisao = RevisaoServico(provedor_servico, app.state.ferramentas, app.state.configuracao)
    kiro = kiro_de(provedor_servico.provedor)
    if kiro is not None:  # modelo por parte do sistema (configuravel no painel; o catalogo e o da conta Kiro)
        kiro.modelo_de = app.state.configuracao.modelo_para
        kiro.esforco_de = app.state.configuracao.esforco_para
        kiro.alternativas_de = app.state.configuracao.alternativas_para
    app.state.modelos = CatalogoModelos(resolver_cli(cfg.app_kiro_cli_path))  # lista da conta (somente leitura)
    app.state.token = carregar_token(cfg)
    app.state.contas = ContasServico(provedor_servico.repo, cfg.app_session_ttl_minutes)  # login por usuario e senha
    app.state.limitador = LimitadorTaxa(cfg.app_rate_limit_per_minute)
    app.state.prefs.registrar_aplicador("limite_requisicoes_por_minuto", lambda v: setattr(app.state.limitador, "limite", int(v)))
    if app.state.memoria.semantica is not None:
        app.state.prefs.registrar_aplicador("busca_semantica", app.state.memoria.semantica.definir_modo)
    # estudo (alimentacao do segundo cerebro) + registro de decisoes/aprendizados ao concluir tarefas reais
    app.state.estudos = EstudoServico(provedor_servico, app.state.memoria, app.state.grafo, app.state.prefs.politica_pastas,
                                      Principal("estudos", cfg.memoria_namespaces))
    provedor_servico.ao_finalizar.append(app.state.estudos.ao_finalizar)
    app.state.prefs.registrar_aplicador("registrar_aprendizados", lambda v: setattr(app.state.estudos, "registrar_aprendizados", bool(v)))
    _melhorias_orquestrador(app, cfg, provedor_servico)
    app.state.prefs.aplicar_todos()  # aplica as preferencias salvas aos componentes ja criados
    app.state.encerrando = threading.Event()
    app.state.hosts = {"127.0.0.1", "localhost", "::1", f"127.0.0.1:{cfg.app_port}", f"localhost:{cfg.app_port}"}
    app.state.hosts |= {h.strip() for h in cfg.app_allowed_hosts.split(",") if h.strip()}

    _registrar_middleware(app, cfg)
    _registrar_handlers(app)
    app.include_router(publico)
    app.include_router(ra)
    app.include_router(r)
    app.include_router(rm)
    app.include_router(rf)
    app.include_router(ri)
    app.include_router(rp)
    app.include_router(rq)
    app.include_router(rs)
    app.include_router(rv)
    app.include_router(rj)
    app.include_router(rx)
    app.include_router(rc)
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
            conta = request.url.path.startswith("/api") or app.state.prefs.valor("contar_estaticos_no_limite")
            if conta and not app.state.limitador.permitir(cliente):
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
        espera = getattr(exc, "tentar_em_s", None)  # bloqueio de login: o painel mostra a contagem regressiva
        return JSONResponse(status_code=exc.status, content={"erro": exc.codigo, "mensagem": exc.mensagem,
                                                             **({"tentar_em_s": espera} if espera else {})},
                            headers={"Retry-After": str(espera)} if espera else None)

    @app.exception_handler(RequestValidationError)
    async def _validacao(request: Request, exc: RequestValidationError):  # noqa: ANN202, ARG001
        detalhes = [
            {"local": list(e.get("loc", [])), "tipo": e.get("type", ""), "msg": str(e.get("msg", ""))}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"erro": "validacao", "detalhes": detalhes})
