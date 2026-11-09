"""Rotas HTTP /api/v1. Apenas traducao HTTP <-> casos de uso; sem SQL nem regras."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response
from fastapi.responses import StreamingResponse

from forja import __version__
from forja.adapters.kiro_acp.diagnostico import diagnosticar
from forja.adapters.sqlite import tabelas as T
from forja.dominio.contratos import (
    ConversaIn,
    DecisaoAprovacaoIn,
    DecisaoLoteIn,
    ObjetivoIn,
    ProjetoIn,
    TarefaIn,
    TransicaoIn,
)
from forja.dominio.estados import EstadoTarefa
from forja.observabilidade import recursos as recursos_mod
from forja.orquestracao.servico import Servico
from forja.seguranca.auth import extrair_bearer, token_confere
from forja.servidor import sse

ID = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
ChaveIdem = Annotated[
    str | None, Header(alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
]
ATOR = "operador-local"


def servico(request: Request) -> Servico:
    return request.app.state.servico


def autenticar(request: Request) -> None:
    esperado = request.app.state.token
    if esperado is None:
        return
    if not token_confere(extrair_bearer(request.headers.get("authorization")), esperado):
        raise HTTPException(status_code=401, detail="Credenciais ausentes ou invalidas.",
                            headers={"WWW-Authenticate": "Bearer"})


publico = APIRouter(prefix="/api/v1")
r = APIRouter(prefix="/api/v1", dependencies=[Depends(autenticar)])
Svc = Annotated[Servico, Depends(servico)]


def _criado(resp: Response, resultado: tuple[dict, bool]) -> dict:
    corpo, repetida = resultado
    resp.status_code = 201
    if repetida:
        resp.headers["Idempotent-Replayed"] = "true"
    return corpo


@publico.get("/saude")
def saude() -> dict[str, str]:
    return {"status": "ok", "versao": __version__}


@r.get("/recursos")
def recursos(request: Request) -> dict[str, Any]:
    cfg = request.app.state.config
    m = recursos_mod.coletar(cfg.app_data_dir)
    return {"metricas": m, **recursos_mod.decidir_perfil(m, cfg.app_reserve_free_ram_gb, cfg.app_resource_profile)}


@r.get("/kiro/status")
def kiro_status(request: Request) -> dict[str, Any]:
    """Diagnostico sob demanda (versao, login sim/nao, handshake ACP). Nao inicia sessao nem consome creditos."""
    cfg = request.app.state.config
    d = diagnosticar(cfg.app_kiro_cli_path, cfg.app_kiro_agent, cfg.app_kiro_model)
    return {**d, "acp_habilitado": cfg.app_kiro_acp_enabled}


@r.get("/agentes")
def agentes(s: Svc) -> list[dict[str, Any]]:
    p = s.provedor
    return [{"id": p.id, "mock": p.mock, "provedor": "mock" if p.mock else "kiro"}]


@r.post("/projetos")
def criar_projeto(d: ProjetoIn, resp: Response, s: Svc, chave: ChaveIdem = None) -> dict:
    return _criado(resp, s.criar_projeto(d, chave))


@r.get("/projetos")
def listar_projetos(s: Svc) -> list[dict]:
    return s.listar(T.Projeto)


@r.get("/projetos/{id_}")
def obter_projeto(id_: ID, s: Svc) -> dict:
    return s.obter(T.Projeto, id_)


@r.post("/objetivos")
def criar_objetivo(d: ObjetivoIn, resp: Response, s: Svc, chave: ChaveIdem = None) -> dict:
    return _criado(resp, s.criar_objetivo(d, chave))


@r.get("/objetivos")
def listar_objetivos(s: Svc, projeto_id: str | None = Query(default=None, max_length=64)) -> list[dict]:
    return s.listar(T.Objetivo, projeto_id=projeto_id)


@r.get("/objetivos/{id_}")
def obter_objetivo(id_: ID, s: Svc) -> dict:
    return s.progresso_objetivo(id_)


@r.post("/tarefas")
def criar_tarefa(d: TarefaIn, resp: Response, s: Svc, chave: ChaveIdem = None) -> dict:
    return _criado(resp, s.criar_tarefa(d, chave))


@r.get("/tarefas")
def listar_tarefas(
    s: Svc,
    projeto_id: str | None = Query(default=None, max_length=64),
    objetivo_id: str | None = Query(default=None, max_length=64),
    estado: EstadoTarefa | None = None,
) -> list[dict]:
    return s.listar(T.Tarefa, projeto_id=projeto_id, objetivo_id=objetivo_id,
                    estado=estado.value if estado else None)


@r.get("/tarefas/{id_}")
def obter_tarefa(id_: ID, s: Svc) -> dict:
    tarefa = s.obter(T.Tarefa, id_)
    return {**tarefa, "execucoes": s.listar(T.Execucao, tarefa_id=id_),
            "evidencias": s.listar(T.Evidencia, tarefa_id=id_), "artefatos": s.listar(T.Artefato, tarefa_id=id_)}


@r.post("/tarefas/{id_}/transicao")
def transicionar(id_: ID, d: TransicaoIn, resp: Response, s: Svc, chave: ChaveIdem = None) -> dict:
    corpo, repetida = s.transicionar(id_, d, ATOR, chave)
    if repetida:
        resp.headers["Idempotent-Replayed"] = "true"
    return corpo


@r.get("/tarefas/{id_}/conversa")
def conversa(id_: ID, s: Svc) -> list[dict]:
    """Conversa da tarefa: secoes do agente (entendimento, resposta, decisoes...) e respostas do desenvolvedor."""
    return s.conversa(id_)


@r.post("/tarefas/{id_}/conversa")
def responder(id_: ID, d: ConversaIn, s: Svc) -> dict:
    """UMA resposta livre cobre todas as decisoes pendentes; com `retomar` (padrao) a execucao continua."""
    return s.responder(id_, d, ATOR)


@r.get("/tarefas/{id_}/contexto")
def contexto(id_: ID, s: Svc) -> list[dict]:
    """O que entrou no prompt de cada execucao, quanto custou (estimado), o que foi omitido e o que foi usado."""
    return s.contexto_da_tarefa(id_)


@r.post("/tarefas/{id_}/execucoes")
def criar_execucao(id_: ID, resp: Response, s: Svc) -> dict:
    resp.status_code = 201
    return s.criar_execucao(id_)


@r.get("/execucoes/{id_}")
def obter_execucao(id_: ID, s: Svc) -> dict:
    return s.obter(T.Execucao, id_)


@r.post("/execucoes/{id_}/iniciar", status_code=202)
def iniciar(id_: ID, s: Svc) -> dict:
    return s.iniciar_execucao(id_, ATOR)


@r.post("/execucoes/{id_}/pausar", status_code=202)
def pausar(id_: ID, s: Svc) -> dict:
    return s.pausar_execucao(id_)


@r.post("/execucoes/{id_}/cancelar", status_code=202)
def cancelar(id_: ID, s: Svc) -> dict:
    return s.cancelar_execucao(id_, "cancelamento solicitado via API", ATOR)


@r.get("/aprovacoes")
def listar_aprovacoes(
    s: Svc, estado: str | None = Query(default=None, pattern="^(pendente|aprovada|negada)$")
) -> list[dict]:
    return s.listar(T.Aprovacao, estado=estado)


@r.post("/aprovacoes/decidir-lote")
def decidir_lote(d: DecisaoLoteIn, s: Svc) -> dict:
    """Uma decisao (e um adendo) para varios pedidos de uma vez."""
    return s.decidir_lote(d, ATOR)


@r.post("/aprovacoes/{id_}/decidir")
def decidir(id_: ID, d: DecisaoAprovacaoIn, s: Svc) -> dict:
    return s.decidir_aprovacao(id_, d, ATOR)


@r.get("/artefatos/{id_}")
def obter_artefato(id_: ID, s: Svc, conteudo: bool = False) -> dict:
    return s.obter_artefato(id_, com_conteudo=conteudo)


@r.get("/locks")
def locks(s: Svc) -> list[dict]:
    return s.listar_locks()


@r.get("/eventos")
def eventos(s: Svc, after_id: int = Query(default=0, ge=0), limite: int = Query(default=200, ge=1, le=1000),
            projeto_id: str | None = Query(default=None, max_length=64)) -> list[dict]:
    return s.eventos_apos(after_id, limite, projeto_id)


# Stream fica no router publico porque EventSource nao envia cabecalho Authorization:
# autentica-se por token em query string (uso local/tunel). Mutacoes continuam exigindo Bearer.
@publico.get("/eventos/stream")
def stream(
    request: Request,
    s: Svc,
    after_id: int | None = Query(default=None, ge=0),
    projeto_id: str | None = Query(default=None, max_length=64),
    follow: bool = True,
    token: str | None = Query(default=None, max_length=256),
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID", max_length=20)] = None,
) -> StreamingResponse:
    esperado = request.app.state.token
    enviado = token or extrair_bearer(request.headers.get("authorization"))
    if esperado is not None and not token_confere(enviado, esperado):
        raise HTTPException(status_code=401, detail="Token invalido para stream.")
    cursor = after_id
    if last_event_id is not None:
        try:
            cursor = max(0, int(last_event_id))
        except ValueError:
            cursor = after_id
    parar = request.app.state.encerrando.is_set
    return StreamingResponse(
        sse.gerar(s, cursor, projeto_id, follow, parar),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
