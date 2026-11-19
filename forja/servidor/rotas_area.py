"""Rotas da bancada do painel (arquivos, busca, simbolos, Git, terminal, Docker, HTTP e assistente de comandos).
So traducao HTTP <-> AreaTrabalho/AssistenteServico. Acao perigosa responde 428 (`confirmacao_necessaria`) com os motivos."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from forja.assistente.servico import AssistenteServico
from forja.orquestracao.area_trabalho import AreaTrabalho
from forja.orquestracao.projetos_servico import MAX_PASTAS
from forja.servidor.rotas import autenticar

ra2 = APIRouter(prefix="/api/v1/area", dependencies=[Depends(autenticar)])
Rel = Annotated[str, Field(min_length=1, max_length=500)]
Raiz = Annotated[int, Field(ge=0, le=MAX_PASTAS)]
IdProjeto = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
Arg = Annotated[str, Field(max_length=4000)]


def _svc(request: Request) -> AreaTrabalho:
    return request.app.state.area


def _assist(request: Request) -> AssistenteServico:
    return request.app.state.assistente


Svc = Annotated[AreaTrabalho, Depends(_svc)]
Assist = Annotated[AssistenteServico, Depends(_assist)]
QRaiz = Annotated[int, Query(ge=0, le=MAX_PASTAS)]
QID = Annotated[str, Query(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
QRel = Annotated[str, Query(min_length=1, max_length=500)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SalvarIn(_In):
    projeto: IdProjeto
    raiz: Raiz
    rel: Rel
    conteudo: Annotated[str, Field(max_length=2_000_000)]
    sha: Annotated[str, Field(max_length=64)] | None = None


class ProblemasIn(_In):
    projeto: IdProjeto
    raiz: Raiz
    rel: Rel
    conteudo: Annotated[str, Field(max_length=2_000_000)] | None = None


class GitAcaoIn(_In):
    projeto: IdProjeto
    raiz: Raiz
    acao: Literal["stage", "unstage", "commit", "discard"]
    arquivos: list[Annotated[str, Field(max_length=500)]] = Field(default_factory=list, max_length=500)
    mensagem: Annotated[str, Field(max_length=2000)] = ""
    confirmado: bool = False


class GitExecIn(_In):
    projeto: IdProjeto
    raiz: Raiz
    args: list[Arg] = Field(min_length=1, max_length=200)
    confirmado: bool = False


class TerminalIn(_In):
    projeto: IdProjeto
    raiz: Raiz
    comando: Annotated[str, Field(min_length=1, max_length=4000)]
    confirmado: bool = False
    tempo_s: Annotated[float, Field(ge=5, le=900)] | None = None


class DockerAcaoIn(_In):
    id: Annotated[str, Field(min_length=1, max_length=256)]
    acao: Literal["start", "stop", "restart", "kill", "rm", "pause", "unpause"]
    confirmado: bool = False


class DockerExecIn(_In):
    args: list[Arg] = Field(min_length=1, max_length=200)
    confirmado: bool = False
    projeto: IdProjeto | None = None
    raiz: Raiz = 0


class HttpIn(_In):
    metodo: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = "GET"
    url: Annotated[str, Field(min_length=8, max_length=8000)]
    cabecalhos: dict[Annotated[str, Field(max_length=200)], Annotated[str, Field(max_length=8000)]] = Field(default_factory=dict, max_length=100)
    corpo: Annotated[str, Field(max_length=5_000_000)] | None = None
    tempo_s: Annotated[float, Field(ge=1, le=120)] = 30
    seguir: bool = True
    verificar_tls: bool = True


class AnalisarIn(_In):
    linha: Annotated[str, Field(max_length=4000)]
    contexto: dict[Annotated[str, Field(max_length=20)], list[Annotated[str, Field(max_length=300)]]] = Field(default_factory=dict, max_length=8)


class ComandoUsuarioIn(_In):
    comando: dict[str, Any] | None = None
    receita: dict[str, Any] | None = None


class PedirIaIn(_In):
    programa: Annotated[str, Field(min_length=1, max_length=60)]
    detalhe: Annotated[str, Field(max_length=500)] = ""
    executar: bool = True


class ImportarIaIn(_In):
    tarefa_id: IdProjeto


# ------------------------------------------------------------------ arquivos
@ra2.get("/arvore")
def arvore(s: Svc, projeto: QID, raiz: QRaiz = 0, rel: Annotated[str, Query(max_length=500)] = "") -> dict[str, Any]:
    return s.listar(projeto, raiz, rel)


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
           incluir: Annotated[str, Query(max_length=60, pattern=r"^[A-Za-z0-9_.*?\-\[\]]*$")] = "", segredos: bool = False) -> dict[str, Any]:
    return s.buscar(projeto, raiz, padrao, regex, incluir, incluir_segredos=segredos)


@ra2.get("/simbolos")
def simbolos(s: Svc, projeto: QID, rel: QRel, raiz: QRaiz = 0) -> dict[str, Any]:
    return s.simbolos(projeto, raiz, rel)


@ra2.get("/definicao")
def definicao(s: Svc, projeto: QID, nome: Annotated[str, Query(min_length=1, max_length=120)], raiz: QRaiz = 0) -> dict[str, Any]:
    return s.definicao(projeto, raiz, nome)


# ------------------------------------------------------------------ Git
@ra2.get("/git")
def git(s: Svc, projeto: QID, raiz: QRaiz = 0,
        operacao: Annotated[str, Query(pattern=r"^(status|log|diff|blame|show|branches)$")] = "status",
        ref: Annotated[str, Query(max_length=120)] = "", arquivo: Annotated[str, Query(max_length=500)] = "",
        limite: Annotated[int, Query(ge=1, le=100)] = 30) -> dict[str, Any]:
    return s.git(projeto, raiz, operacao, ref, arquivo, limite)


@ra2.get("/git/versao")
def git_versao(s: Svc, projeto: QID, rel: QRel, raiz: QRaiz = 0, versao: Annotated[str, Query(max_length=120)] = "HEAD") -> dict[str, Any]:
    return s.git_versao(projeto, raiz, rel, versao)


@ra2.post("/git")
def git_acao(d: GitAcaoIn, s: Svc) -> dict[str, Any]:
    return s.git_acao(d.projeto, d.raiz, d.acao, d.arquivos, d.mensagem, d.confirmado)


@ra2.post("/git/executar")
def git_executar(d: GitExecIn, s: Svc) -> dict[str, Any]:
    return s.git_executar(d.projeto, d.raiz, d.args, d.confirmado)


# ------------------------------------------------------------------ terminal
@ra2.post("/terminal")
def terminal(d: TerminalIn, s: Svc) -> dict[str, Any]:
    return s.terminal(d.projeto, d.raiz, d.comando, d.confirmado, d.tempo_s)


# ------------------------------------------------------------------ Docker
@ra2.get("/docker")
def docker(s: Svc, recurso: Annotated[str, Query(pattern=r"^(containers|imagens|volumes|redes|compose)$")] = "containers") -> list[dict[str, Any]]:
    return s.docker(recurso)


@ra2.get("/docker/logs")
def docker_logs(s: Svc, id: Annotated[str, Query(min_length=1, max_length=256)], linhas: Annotated[int, Query(ge=1, le=5000)] = 200) -> dict[str, Any]:  # noqa: A002
    return s.docker_logs(id, linhas)


@ra2.post("/docker")
def docker_acao(d: DockerAcaoIn, s: Svc) -> dict[str, Any]:
    return s.docker_acao(d.id, d.acao, d.confirmado)


@ra2.post("/docker/executar")
def docker_executar(d: DockerExecIn, s: Svc) -> dict[str, Any]:
    return s.docker_executar(d.args, d.confirmado, d.projeto, d.raiz)


# ------------------------------------------------------------------ HTTP
@ra2.post("/http")
def http(d: HttpIn, s: Svc) -> dict[str, Any]:
    return s.http(d.metodo, d.url, d.cabecalhos, d.corpo, d.tempo_s, d.seguir, d.verificar_tls)


# ------------------------------------------------------------------ assistente de comandos
@ra2.get("/comandos")
def comandos(s: Svc) -> dict[str, Any]:
    cat = s.assistente.atual()
    return {"comandos": [c.model_dump(exclude_defaults=False) for c in cat.comandos], "receitas": [r.model_dump() for r in cat.receitas]}


@ra2.post("/comandos/analisar")
def analisar(d: AnalisarIn, s: Svc) -> dict[str, Any]:
    return {"analise": s.assistente.analisar(d.linha), "sugestoes": s.assistente.sugerir(d.linha, d.contexto)}


@ra2.post("/comandos/usuario")
def comando_usuario(d: ComandoUsuarioIn, a: Assist) -> dict[str, Any]:
    return a.salvar(d.comando, d.receita)


@ra2.delete("/comandos/usuario/{id_}")
def remover_comando(id_: Annotated[str, Field(max_length=80)], a: Assist) -> dict[str, Any]:
    return a.remover(id_)


@ra2.post("/comandos/usuario/{id_}/revisar")
def revisar_comando(id_: Annotated[str, Field(max_length=80)], a: Assist) -> dict[str, Any]:
    return a.revisar(id_)


@ra2.post("/comandos/ia")
def pedir_ia(d: PedirIaIn, a: Assist) -> dict[str, Any]:
    return a.pedir_ia(d.programa, d.detalhe, d.executar)


@ra2.post("/comandos/ia/importar")
def importar_ia(d: ImportarIaIn, a: Assist) -> dict[str, Any]:
    return a.importar(d.tarefa_id)


# ------------------------------------------------------------------ editor: autocompletar de codigo e servidores de linguagem
class ItemCodigoIn(_In):
    ramo: Annotated[str, Field(min_length=3, max_length=60)]
    item: dict[str, Any]
    ramo_meta: dict[str, Any] | None = None


class PedirIaCodigoIn(_In):
    linguagem: Annotated[str, Field(min_length=1, max_length=20)]
    ramo: Annotated[str, Field(max_length=60)] = ""
    pedido: Annotated[str, Field(max_length=500)] = ""
    executar: bool = True


class LspIn(_In):
    projeto: IdProjeto
    raiz: Raiz
    rel: Rel
    texto: Annotated[str, Field(max_length=2_000_000)] = ""
    linha: Annotated[int, Field(ge=0, le=10_000_000)] = 0
    coluna: Annotated[int, Field(ge=0, le=1_000_000)] = 0
    gatilho: Annotated[str, Field(max_length=1)] = ""


class InstalarLspIn(_In):
    servidor: Literal["python", "typescript", "html", "css", "csharp"]
    confirmado: bool = False


def _prefs_editor(request: Request) -> dict[str, Any]:
    p = request.app.state.prefs
    return {k: p.valor(k) for k in ("autocompletar_codigo", "autocompletar_automatico", "autocompletar_atraso_ms", "autocompletar_max",
                                    "autocompletar_fontes", "autocompletar_ramos_desligados", "lsp_ativo", "terminal_assistente")}


@ra2.get("/editor")
def editor(request: Request) -> dict[str, Any]:
    """Configuracao do editor para o painel: assistentes de autocompletar e servidores de linguagem."""
    g = request.app.state.area.gerente_lsp
    return {"preferencias": _prefs_editor(request), "lsp": g.estado() if g is not None else None,
            "ramos": request.app.state.codigo.catalogo.resumo()}


@ra2.get("/codigo/catalogo")
def codigo_catalogo(request: Request, linguagem: Annotated[str, Query(min_length=1, max_length=20)]) -> dict[str, Any]:
    desligados = request.app.state.prefs.valor("autocompletar_ramos_desligados") or []
    return request.app.state.codigo.catalogo.catalogo(linguagem, desligados)


@ra2.post("/codigo/item")
def codigo_item(d: ItemCodigoIn, request: Request) -> dict[str, Any]:
    return request.app.state.codigo.salvar_item(d.ramo, d.item, d.ramo_meta)


@ra2.delete("/codigo/item")
def codigo_remover(request: Request, ramo: Annotated[str, Query(min_length=3, max_length=60)],
                   rotulo: Annotated[str, Query(min_length=1, max_length=80)]) -> dict[str, Any]:
    request.app.state.codigo.catalogo.remover_item(ramo, rotulo)
    return {"removido": rotulo}


@ra2.post("/codigo/ramos/{ramo}/revisar")
def codigo_revisar(ramo: Annotated[str, Field(min_length=3, max_length=60)], request: Request) -> dict[str, Any]:
    return {"revisados": request.app.state.codigo.catalogo.revisar(ramo)}


@ra2.post("/codigo/ia")
def codigo_ia(d: PedirIaCodigoIn, request: Request) -> dict[str, Any]:
    return request.app.state.codigo.pedir_ia(d.linguagem, d.ramo, d.pedido, d.executar)


@ra2.post("/codigo/ia/importar")
def codigo_ia_importar(d: ImportarIaIn, request: Request) -> dict[str, Any]:
    return request.app.state.codigo.importar(d.tarefa_id)


@ra2.get("/lsp")
def lsp_estado(request: Request) -> dict[str, Any]:
    g = request.app.state.area.gerente_lsp
    return g.estado() if g is not None else {"ativo": False, "servidores": []}


@ra2.post("/lsp/instalar")
def lsp_instalar(d: InstalarLspIn, request: Request) -> dict[str, Any]:
    from forja.adapters.lsp.cliente import ErroLsp
    from forja.dominio.erros import ConfirmacaoNecessaria, ValidacaoDominio

    g = request.app.state.area.gerente_lsp
    if g is None:
        raise ValidacaoDominio("servidores de linguagem indisponíveis neste servidor")
    if not d.confirmado:
        alvo = next(s for s in g.estado()["servidores"] if s["id"] == d.servidor)
        raise ConfirmacaoNecessaria(f"Instalar o servidor de linguagem {alvo['rotulo']}?", [
            f"baixa pacotes da internet ({alvo['instalacao']})", "fica só na pasta de dados da Forja; não altera o Node/.NET do sistema"], "medio")
    try:
        return g.instalar(d.servidor)
    except ErroLsp as e:
        raise ValidacaoDominio(str(e)) from e


@ra2.post("/lsp/{acao}")
def lsp_acao(acao: Literal["completar", "explicar", "definicao", "diagnosticos", "fechar"], d: LspIn, s: Svc) -> dict[str, Any]:
    return s.lsp(acao, d.projeto, d.raiz, d.rel, d.texto, d.linha, d.coluna, d.gatilho)
