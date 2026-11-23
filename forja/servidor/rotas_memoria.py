"""Rotas de memoria / segundo cerebro. Apenas traducao HTTP <-> ServicoMemoria; ACL e regras vivem no servico."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from forja.memoria.contratos import (
    ArestaIn,
    IngerirIn,
    MemoriaAtualizaIn,
    MemoriaIn,
    NoIn,
    PropostaIn,
    ResolverConflitoIn,
    RevalidarIn,
    TransicaoMemoriaIn,
    ValidarIn,
    VincularEvidenciaIn,
)
from forja.memoria.modelo import Principal, TipoMemoria
from forja.memoria.rotulagem import RotulagemServico
from forja.orquestracao.memoria_servico import ServicoMemoria
from forja.servidor.rotas import ATOR, ID, autenticar

rm = APIRouter(prefix="/api/v1", dependencies=[Depends(autenticar)])


def _memoria(request: Request) -> ServicoMemoria:
    return request.app.state.memoria


def _principal(request: Request) -> Principal:
    return Principal(ATOR, request.app.state.config.memoria_namespaces)


Mem = Annotated[ServicoMemoria, Depends(_memoria)]
Pr = Annotated[Principal, Depends(_principal)]


@rm.post("/memorias", status_code=201)
def criar(d: MemoriaIn, s: Mem, p: Pr, evitar_duplicata: bool = False) -> dict[str, Any]:
    """evitar_duplicata=true (usado pelos agentes): se ja existe nota ativa parecida no namespace, devolve ELA (duplicata=true)."""
    if evitar_duplicata:
        existente = s.parecida(p, d.namespace, d.titulo, d.conteudo or d.resumo)
        if existente is not None:
            return {**existente, "duplicata": True}
    return s.criar(p, d, ATOR)


class OrganizarIaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    namespaces: list[Annotated[str, Field(max_length=200)]] | None = Field(None, max_length=10)
    foco: Annotated[str, Field(max_length=500)] = ""
    executar: bool = True


class ImportarPlanoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tarefa_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]


class AvaliarNotaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    titulo: Annotated[str, Field(max_length=200)] = ""
    conteudo: Annotated[str, Field(max_length=100_000)] = ""
    tags: list[Annotated[str, Field(max_length=50)]] = Field(default_factory=list, max_length=30)


# ------------------------------------------------------------------ pastas do segundo cerebro (ADR-029)
Ns = Annotated[str, Field(min_length=1, max_length=200)]


class PastaIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    namespace: Ns
    descricao: Annotated[str, Field(max_length=300)] = ""


class MoverIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[Annotated[str, Field(max_length=64)]] = Field(min_length=1, max_length=500)
    destino: Ns


class RenomearIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origem: Ns
    destino: Ns


class ProporPastaIn(BaseModel):
    """Pedido de um AGENTE (MCP): vira sugestao na fila de revisao; so o usuario aplica."""
    model_config = ConfigDict(extra="forbid")
    acao: Literal["criar", "mover", "renomear"]
    destino: Ns
    origem: Annotated[str, Field(max_length=200)] = ""
    ids: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list, max_length=500)
    descricao: Annotated[str, Field(max_length=300)] = ""
    motivo: Annotated[str, Field(max_length=500)] = ""


@rm.get("/memorias/pastas")
def pastas(request: Request, p: Pr) -> dict[str, Any]:
    return request.app.state.pastas.arvore(p)


@rm.get("/memorias/pastas/notas")
def notas_da_pasta(request: Request, p: Pr, namespace: Annotated[str, Query(min_length=1, max_length=200)],
                   subpastas: bool = False, limite: Annotated[int, Query(ge=1, le=1000)] = 500) -> dict[str, Any]:
    return request.app.state.pastas.notas(p, namespace, subpastas, limite)


@rm.post("/memorias/pastas", status_code=201)
def criar_pasta(d: PastaIn, request: Request, p: Pr) -> dict[str, Any]:
    return request.app.state.pastas.criar(p, d.namespace, d.descricao, ATOR)


@rm.delete("/memorias/pastas", status_code=204)
def remover_pasta(request: Request, p: Pr, namespace: Annotated[str, Query(min_length=1, max_length=200)]) -> Response:
    request.app.state.pastas.remover(p, namespace)
    return Response(status_code=204)


@rm.post("/memorias/pastas/mover")
def mover_notas(d: MoverIn, request: Request, p: Pr) -> dict[str, Any]:
    return request.app.state.pastas.mover(p, d.ids, d.destino, ATOR)


@rm.post("/memorias/pastas/renomear")
def renomear_pasta(d: RenomearIn, request: Request, p: Pr) -> dict[str, Any]:
    return request.app.state.pastas.renomear(p, d.origem, d.destino, ATOR)


@rm.post("/memorias/pastas/propor", status_code=201)
def propor_pasta(d: ProporPastaIn, request: Request, p: Pr) -> dict[str, Any]:
    return request.app.state.pastas.propor(p, d.acao, {"destino": d.destino, "origem": d.origem, "ids": d.ids, "descricao": d.descricao},
                                           d.motivo, "agente:mcp")


@rm.get("/memorias/saude")
def saude(request: Request, p: Pr, namespace: Annotated[list[str] | None, Query(max_length=10)] = None,
          min_notas: Annotated[int, Query(ge=2, le=20)] = 2, base: bool = False) -> dict[str, Any]:
    """Modularidade do grafo (ADR-028): tamanho das notas, tags, orfas, links fantasmas e trechos repetidos entre notas."""
    return request.app.state.modularidade.saude(p, namespace, min_notas, incluir_base=base)


@rm.post("/memorias/organizar-ia")
def organizar_ia(d: OrganizarIaIn, request: Request, p: Pr) -> dict[str, Any]:
    """Pede a um agente o plano de 'organizar e deduplicar' (modulos, ligacoes, fusoes, divisoes, tags) -> fila de revisao."""
    return request.app.state.modularidade.pedir_ia(p, d.namespaces, d.foco, d.executar)


@rm.post("/memorias/organizar-ia/importar")
def organizar_ia_importar(d: ImportarPlanoIn, request: Request, p: Pr) -> dict[str, Any]:
    return request.app.state.modularidade.importar_plano(p, d.tarefa_id)


@rm.post("/memorias/avaliar")
def avaliar(d: AvaliarNotaIn) -> dict[str, Any]:
    """Avisos de modularidade de uma nota antes de gravar (tamanho, ligacoes, tags, titulo)."""
    from forja.orquestracao.modularidade import avaliar_nota

    return {"avisos": avaliar_nota(d.titulo, d.conteudo, d.tags)}


@rm.get("/memorias/navegar")
def navegar_topico(request: Request, p: Pr, ref: Annotated[str, Query(min_length=1, max_length=200)],
                   conteudo: bool = False) -> dict[str, Any]:
    """Um topico do segundo cerebro e so a vizinhanca imediata (pai, subtopicos, relacionados), com resumos.
    `conteudo=true` traz o corpo do proprio topico. Base da Forja + notas do usuario, com ACL em cada ponta."""
    from forja.memoria.base import navegar

    return navegar(request.app.state.memoria.repo, p, ref, conteudo)


@rm.get("/memorias/revisao")
def fila_revisao(request: Request, p: Pr, limite: Annotated[int, Query(ge=1, le=200)] = 100) -> dict[str, Any]:
    """Fila de revisao: notas candidatas + sugestoes da organizacao automatica (duplicata, desatualizada, ligacao)."""
    return request.app.state.organizador.fila(p, limite)


@rm.post("/memorias/organizar")
def organizar(request: Request) -> dict[str, Any]:
    """Roda a organizacao agora (local, sem IA). So cria sugestoes; nada muda sem voce aceitar."""
    return request.app.state.organizador.organizar()


class DecisaoSugestaoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aceitar: bool
    vencedora_id: Annotated[str, Field(max_length=64)] | None = None  # duplicatas: qual nota fica


@rm.post("/memorias/sugestoes/{id_}/decidir")
def decidir_sugestao(id_: ID, d: DecisaoSugestaoIn, request: Request, p: Pr) -> dict[str, Any]:
    return request.app.state.organizador.decidir(p, id_, d.aceitar, ATOR, d.vencedora_id)


@rm.get("/busca/semantica")
def estado_semantica(s: Mem) -> dict[str, Any]:
    """Nivel da busca semantica, disponibilidade (dependencia/RAM), vetores prontos e velocidade medida."""
    return s.semantica.estado() if s.semantica is not None else {"modo": "inativo", "disponivel": False, "motivo": "desligada"}


@rm.get("/memorias/buscar")
def buscar(
    s: Mem, p: Pr, q: Annotated[str, Query(min_length=1, max_length=300)],
    namespace: Annotated[list[str] | None, Query(max_length=10)] = None,
    fonte: Annotated[list[Literal["memoria", "codigo"]] | None, Query(max_length=2)] = None,
    tipo: Annotated[list[TipoMemoria] | None, Query(max_length=6)] = None,
    limite: Annotated[int, Query(ge=1, le=50)] = 10,
    apenas_validadas: bool = False,
    incluir_inativas: bool = False,
    todos: bool = False,
) -> dict[str, Any]:
    """Sem `namespace`: todos os namespaces que esta instancia permite (o segundo cerebro do usuario fica em `pessoal`; `publico`
    e o framework inicial). `todos` e mantido por compatibilidade (MCP dos agentes) e hoje equivale ao padrao (ADR-029)."""
    _ = todos
    alvo = namespace or sorted(p.namespaces)
    return s.buscar(p, q, alvo, tuple(fonte or ("memoria", "codigo")),
                    [x.value for x in tipo] if tipo else None, limite,
                    apenas_validadas, incluir_inativas)


@rm.post("/memorias/resolver-conflito")
def resolver_conflito(d: ResolverConflitoIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.resolver_conflito(p, d, ATOR)


@rm.post("/tarefas/{tarefa_id}/propor-memoria")
def propor_memoria(tarefa_id: ID, d: PropostaIn, request: Request, p: Pr, resposta: Response) -> dict[str, Any]:
    """Segundo cerebro: gera uma memoria CANDIDATA a partir da tarefa concluida (idempotente; nunca valida)."""
    r = request.app.state.propostas.propor_de_tarefa(p, tarefa_id, d.namespace, ATOR)
    resposta.status_code = 201 if r["criada"] else 200
    return r


@rm.post("/memorias/ingerir")
def ingerir(d: IngerirIn, s: Mem, p: Pr, request: Request) -> dict[str, Any]:
    from forja.seguranca.pastas import aplicar

    with aplicar(request.app.state.prefs.politica_pastas()):  # pastas proibidas da tela valem tambem para o segundo cerebro
        return s.ingerir_diretorio(p, d)


@rm.get("/memorias/estatisticas")
def estatisticas(s: Mem, p: Pr) -> dict[str, Any]:
    return s.estatisticas(p)


@rm.get("/memorias/{id_}")
def obter(id_: ID, s: Mem, p: Pr) -> dict[str, Any]:
    return s.obter(p, id_)


@rm.patch("/memorias/{id_}")
def atualizar(id_: ID, d: MemoriaAtualizaIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.atualizar(p, id_, d, ATOR)


@rm.post("/memorias/{id_}/transicao")
def transicionar(id_: ID, d: TransicaoMemoriaIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.transicionar(p, id_, d, ATOR)


@rm.post("/memorias/{id_}/evidencias")
def vincular(id_: ID, d: VincularEvidenciaIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.vincular_evidencia(p, id_, d.evidencia_id, ATOR)


@rm.post("/memorias/{id_}/validar")
def validar(id_: ID, d: ValidarIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.validar(p, id_, d, ATOR)


@rm.post("/memorias/{id_}/revalidar")
def revalidar(id_: ID, d: RevalidarIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.revalidar(p, id_, d, ATOR)


@rm.delete("/memorias/{id_}", status_code=204)
def remover(id_: ID, s: Mem, p: Pr) -> Response:
    s.remover(p, id_, ATOR)
    return Response(status_code=204)


@rm.post("/conhecimento/nos", status_code=201)
def criar_no(d: NoIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.criar_no(p, d, ATOR)


@rm.post("/conhecimento/arestas", status_code=201)
def criar_aresta(d: ArestaIn, s: Mem, p: Pr) -> dict[str, Any]:
    return s.criar_aresta(p, d, ATOR)


@rm.get("/conhecimento/nos/{id_}/vizinhos")
def vizinhos(id_: ID, s: Mem, p: Pr, saltos: Annotated[int, Query(ge=1, le=2)] = 1,
             tipo: Annotated[list[str] | None, Query(max_length=15)] = None) -> dict[str, Any]:
    return s.vizinhos(p, id_, saltos, tipo)


# ------------------------------------------------------------------ 4.8: rotulagem da busca sobre o corpus real
NomeNs = Annotated[str, Field(min_length=1, max_length=80)]


class CandidatosIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consulta: Annotated[str, Field(min_length=2, max_length=300)]
    namespaces: list[NomeNs] = Field(default_factory=list, max_length=10)


class RotuloIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    consulta: Annotated[str, Field(min_length=2, max_length=300)]
    namespaces: list[NomeNs] = Field(default_factory=list, max_length=10)
    relevantes: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list, max_length=50)
    vistos: list[Annotated[str, Field(max_length=64)]] = Field(min_length=1, max_length=60)
    categoria: Annotated[str, Field(max_length=40)] = "geral"


def _rotulagem(request: Request) -> RotulagemServico:
    return request.app.state.rotulagem


Rot = Annotated[RotulagemServico, Depends(_rotulagem)]


@rm.get("/busca/rotulagem")
def rotulagem(r: Rot, p: Pr, k: Annotated[int, Query(ge=1, le=10)] = 5) -> dict[str, Any]:
    return r.estado(p, k)


@rm.post("/busca/rotulagem/candidatos")
def candidatos(d: CandidatosIn, r: Rot, p: Pr) -> dict[str, Any]:
    return r.candidatos(p, d.consulta, d.namespaces or None)


@rm.post("/busca/rotulagem/casos", status_code=201)
def salvar_rotulo(d: RotuloIn, r: Rot, p: Pr) -> dict[str, Any]:
    ns = r._namespaces(p, d.namespaces or None)
    return r.salvar(d.consulta, d.relevantes, d.vistos, ns, d.categoria, d.expected_version)


@rm.delete("/busca/rotulagem/casos/{id_}", status_code=204)
def remover_rotulo(id_: Annotated[str, Field(max_length=64)], r: Rot, expected_version: Annotated[int, Query(ge=0)]) -> Response:
    r.remover(id_, expected_version)
    return Response(status_code=204)