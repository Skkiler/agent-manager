"""Catalogo de ferramentas N0 (orientacao mestra, secao 13): contrato, validacao de entrada, raizes autorizadas,
fallback e custo observado. Nenhuma ferramenta executa shell, acessa a rede ou escreve em disco."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from forja.dominio.erros import ErroDominio, NaoEncontrado, ValidacaoDominio
from forja.ferramentas.agenda import ler_agenda
from forja.ferramentas.amostra import amostra_arquivo
from forja.ferramentas.caminhos import resolver_dentro
from forja.ferramentas.contrato import ResultadoFerramenta, montar
from forja.ferramentas.conversor import converter
from forja.ferramentas.diff import resumir_diff
from forja.ferramentas.email_mbox import ler_mbox
from forja.ferramentas.esquema import inspecionar_sqlite
from forja.ferramentas.logs import agrupar_falhas
from forja.ferramentas.mapa import mapa_repositorio
from forja.ferramentas.orcamento import orcar_tokens
from forja.ferramentas.outline import outline_arquivo
from forja.ferramentas.segredos import varrer
from forja.ferramentas.testes import resumir_pytest
from forja.ferramentas.vault import indexar_vault
from forja.seguranca.pastas import PoliticaPastas, aplicar, proibido

log = logging.getLogger("forja.ferramentas")
TEXTO_MAX = 2_000_000
Texto = Annotated[str, StringConstraints(max_length=TEXTO_MAX)]
Caminho = Annotated[str, StringConstraints(min_length=1, max_length=500)]


class FerramentaFalhou(ErroDominio):
    codigo = "ferramenta_falhou"
    status = 500


class SemResultado(Exception):
    """A ferramenta rodou mas nao produziu nada util: aciona o fallback (nunca usado para recusas de seguranca)."""


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntTexto(_Base):
    texto: Texto


class EntCaminho(_Base):
    caminho: Caminho


class EntMapa(_Base):
    caminho: Caminho = "."


class EntAmostra(_Base):
    caminho: Caminho
    inicio: int = Field(1, ge=1)
    linhas: int = Field(60, ge=1, le=200)


class EntAgenda(_Base):
    caminho: Caminho
    de: str = ""
    ate: str = ""
    limite: int = Field(50, ge=1, le=500)


class EntMbox(_Base):
    caminho: Caminho
    de: str = ""
    assunto: str = ""
    limite: int = Field(20, ge=1, le=100)
    incluir_corpo: bool = False
    mascarar_enderecos: bool = True


class EntNada(_Base):
    pass


class EntJiraBuscar(_Base):
    jql: Annotated[str, StringConstraints(max_length=500)] = ""
    limite: int | None = Field(None, ge=1, le=50)


class EntJiraObter(_Base):
    chave: Annotated[str, StringConstraints(min_length=3, max_length=40)]


class EntGhIssues(_Base):
    repo: Annotated[str, StringConstraints(min_length=3, max_length=201)]
    estado: str = "open"
    limite: int | None = Field(None, ge=1, le=50)


class EntGhObter(_Base):
    repo: Annotated[str, StringConstraints(min_length=3, max_length=201)]
    numero: int = Field(ge=1, le=10_000_000)


class EntAgendaUrl(_Base):
    de: str = ""
    ate: str = ""
    limite: int | None = Field(None, ge=1, le=50)


Lim = Annotated[int | None, Field(None, ge=1, le=50)]
TextoEscrita = Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class EntTrelloCartoes(_Base):
    quadro: Annotated[str, StringConstraints(min_length=24, max_length=24)]
    limite: Lim = None


class EntNotion(_Base):
    base: Annotated[str, StringConstraints(min_length=32, max_length=36)]
    limite: Lim = None


class EntGoogleAgenda(_Base):
    calendario: Annotated[str, StringConstraints(min_length=1, max_length=250)] = "primary"
    de: str = ""
    ate: str = ""
    limite: Lim = None


class EntGmail(_Base):
    rotulo: Annotated[str, StringConstraints(min_length=1, max_length=60)] = "INBOX"
    limite: int | None = Field(None, ge=1, le=10)


class EntJiraComentar(_Base):
    chave: Annotated[str, StringConstraints(min_length=3, max_length=40)]
    texto: TextoEscrita


class EntJiraTransicao(_Base):
    chave: Annotated[str, StringConstraints(min_length=3, max_length=40)]
    para: Annotated[str, StringConstraints(min_length=1, max_length=60)]


class EntGhComentar(_Base):
    repo: Annotated[str, StringConstraints(min_length=3, max_length=201)]
    numero: int = Field(ge=1, le=10_000_000)
    texto: TextoEscrita


class EntTrelloCartao(_Base):
    lista: Annotated[str, StringConstraints(min_length=24, max_length=24)]
    nome: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    descricao: Annotated[str, StringConstraints(max_length=4000)] = ""


class EntBuscaWeb(_Base):
    consulta: Annotated[str, StringConstraints(min_length=2, max_length=300)]
    limite: int | None = Field(None, ge=1, le=20)


class EntLerPagina(_Base):
    url: Annotated[str, StringConstraints(min_length=10, max_length=2000)]


NomeVar = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")]


class EntEnv(_Base):
    caminho: Annotated[str, StringConstraints(min_length=4, max_length=500)] = ".env"
    chaves: list[NomeVar] = Field(default_factory=list, max_length=50)
    formatos: dict[NomeVar, str] = Field(default_factory=dict, max_length=50)
    comparar: dict[NomeVar, Annotated[str, StringConstraints(max_length=500)]] = Field(default_factory=dict, max_length=10)
    exemplo: Annotated[str, StringConstraints(max_length=500)] | None = ".env.example"


def _env(e: EntEnv, c: Contexto) -> ResultadoFerramenta:
    """Le o .env DENTRO da Forja (nunca o devolve). So arquivos .env/.env.* das pastas permitidas; protegidas e proibidas nunca."""
    from forja.ferramentas.ambiente_env import NOME_ENV, verificar
    from forja.seguranca.pastas import protegido

    raiz, rel = c.resolver(e.caminho)
    p = Path(rel)
    if not NOME_ENV.fullmatch(p.name):
        raise ValidacaoDominio("env.verificar so aceita arquivos .env ou .env.<nome>")
    pasta = resolver_dentro(raiz, p.parent.as_posix() or ".", diretorio=True)
    arquivo = pasta / p.name
    if arquivo.is_symlink() or not arquivo.is_file() or protegido(arquivo) or proibido(arquivo):
        raise ValidacaoDominio("arquivo .env nao encontrado nas pastas permitidas")
    exemplo = None
    if e.exemplo:  # modelo (.env.example): mesma pasta, so o NOME do arquivo (sem subir de diretorio)
        nome = Path(e.exemplo).name
        candidato = pasta / nome
        if NOME_ENV.fullmatch(nome) and candidato.is_file() and not candidato.is_symlink() and not proibido(candidato):
            exemplo = candidato
    return verificar(arquivo, list(e.chaves), dict(e.formatos), dict(e.comparar), exemplo)


class EntLogs(_Base):
    texto: Texto
    limite: int = Field(10, ge=1, le=30)


class EntPytest(_Base):
    texto: Texto
    limite: int = Field(10, ge=1, le=30)


class EntConverter(_Base):
    texto: Texto
    de: str
    para: str
    delimitador: Annotated[str, StringConstraints(min_length=1, max_length=1)] = ","
    neutralizar_formulas: bool = True


class ItemOrcamento(_Base):
    id: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    texto: Texto


class EntOrcar(_Base):
    itens: list[ItemOrcamento] = Field(max_length=200)
    orcamento: int = Field(ge=1, le=1_000_000)
    teto_item: int | None = Field(None, ge=1)


@dataclass
class Contexto:
    raizes: tuple[Path, ...] = ()
    integracoes: Any = None  # IntegracaoServico (opcional): ferramentas de rede so funcionam se a integracao estiver pronta
    acoes: Any = None  # AcoesExternasServico (opcional): escrita so como PROPOSTA que o operador aprova

    def propor(self, id_: str, acao: str, params: dict[str, Any]) -> ResultadoFerramenta:
        """Nunca escreve: cria uma acao externa pendente e devolve a frase que o operador vai aprovar ou negar."""
        if self.acoes is None:
            raise ValidacaoDominio("acoes externas desligadas neste servidor")
        a, criada = self.acoes.propor(id_, acao, params, solicitado_por="ferramenta")
        resumo = (f"Aguardando aprovacao do operador ({a['id']}): {a['descricao']}" if a["estado"] == "pendente"
                  else f"Proposta {a['id']} ja existe e esta '{a['estado']}'")
        return montar(f"{id_}.propor_{acao}", "", resumo, {"acao_externa": a["id"], "estado": a["estado"], "nova": criada}, False,
                      ["nada foi enviado ao servico: a escrita so acontece se o operador aprovar"])

    def integracao(self, id_: str, acao: str, params: dict[str, Any]) -> ResultadoFerramenta:
        if self.integracoes is None:
            raise ValidacaoDominio("integracoes de rede desligadas neste servidor")
        return self.integracoes.executar(id_, acao, params)

    def resolver(self, caminho: str) -> tuple[Path, str]:
        """Escolhe a raiz autorizada que contem `caminho` (absoluto ou relativo) e devolve (raiz, relativo)."""
        if not self.raizes:
            raise ValidacaoDominio("ferramentas de arquivo desligadas: defina APP_TOOLS_ROOTS")
        p = Path(caminho)
        if p.is_absolute():
            for raiz in self.raizes:
                try:
                    return raiz, p.resolve().relative_to(raiz.resolve()).as_posix() or "."
                except ValueError:
                    continue
            raise ValidacaoDominio("caminho fora das raizes autorizadas")
        for raiz in self.raizes:
            if (raiz / p).exists() or (raiz / p).is_symlink():
                return raiz, caminho
        return self.raizes[0], caminho


Rodar = Callable[[Any, Contexto], ResultadoFerramenta]


@dataclass(frozen=True)
class Ferramenta:
    id: str
    descricao: str
    entrada: type[BaseModel]
    rodar: Rodar
    usa_arquivos: bool = False
    risco: str = "leitura"
    fallback: str | None = None
    integracao: str | None = None  # id da integracao de rede exigida (configurada e pronta)


@dataclass
class _Uso:
    chamadas: int = 0
    erros: int = 0
    fallbacks: int = 0
    tokens_origem: int = 0
    tokens_resumo: int = 0
    ms: float = 0.0


def _outline(e: EntCaminho, c: Contexto) -> ResultadoFerramenta:
    raiz, rel = c.resolver(e.caminho)
    r = outline_arquivo(raiz, rel)
    if not r.dados["simbolos"]:
        raise SemResultado("sem simbolos")
    return r


def _arquivo(fn: Callable[..., ResultadoFerramenta]) -> Rodar:
    def rodar(e: Any, c: Contexto) -> ResultadoFerramenta:
        raiz, rel = c.resolver(e.caminho)
        extras = {k: v for k, v in e.model_dump().items() if k != "caminho"}
        return fn(raiz, rel, **extras)

    return rodar


FERRAMENTAS: tuple[Ferramenta, ...] = (
    Ferramenta("codigo.outline", "Simbolos e linhas de um arquivo, sem o corpo.", EntCaminho, _outline, True,
               fallback="texto.amostra"),
    Ferramenta("texto.amostra", "Trecho numerado de um arquivo de texto.", EntAmostra, _arquivo(amostra_arquivo), True),
    Ferramenta("repo.mapa", "Linguagens, pastas, entradas e configuracao de um repositorio.", EntMapa,
               _arquivo(mapa_repositorio), True),
    Ferramenta("segredos.varrer", "Possiveis segredos (arquivo:linha, sem o valor).", EntMapa, _arquivo(varrer), True),
    Ferramenta("sql.inspecionar", "Esquema de um banco SQLite (somente leitura, sem linhas).", EntCaminho,
               _arquivo(inspecionar_sqlite), True),
    Ferramenta("vault.indexar", "Notas Markdown (estilo Obsidian): links, backlinks, tags, orfas.", EntMapa, _arquivo(indexar_vault), True),
    Ferramenta("agenda.ler_ics", "Eventos de um arquivo .ics local, por periodo.", EntAgenda, _arquivo(ler_agenda), True),
    Ferramenta("email.ler_mbox", "Mensagens de uma exportacao .mbox local (enderecos mascarados).", EntMbox, _arquivo(ler_mbox), True),
    Ferramenta("jira.buscar", "Issues do Jira (JQL restrito aos projetos permitidos). Somente leitura.", EntJiraBuscar,
               lambda e, c: c.integracao("jira", "buscar", e.model_dump(exclude_none=True)), integracao="jira"),
    Ferramenta("jira.obter_issue", "Uma issue do Jira (resumo, descricao e ultimos comentarios).", EntJiraObter,
               lambda e, c: c.integracao("jira", "obter", e.model_dump()), integracao="jira"),
    Ferramenta("jira.listar_projetos", "Projetos do Jira permitidos nesta integracao.", EntNada,
               lambda e, c: c.integracao("jira", "projetos", {}), integracao="jira"),
    Ferramenta("github.listar_issues", "Issues e PRs de um repositorio permitido. Somente leitura.", EntGhIssues,
               lambda e, c: c.integracao("github", "listar_issues", e.model_dump(exclude_none=True)), integracao="github"),
    Ferramenta("github.obter_issue", "Uma issue ou PR de um repositorio permitido.", EntGhObter,
               lambda e, c: c.integracao("github", "obter_issue", e.model_dump()), integracao="github"),
    Ferramenta("agenda.ler_ics_url", "Eventos da agenda por endereco .ics secreto (guardado no ambiente).", EntAgendaUrl,
               lambda e, c: c.integracao("agenda_ics_url", "eventos", e.model_dump(exclude_none=True)), integracao="agenda_ics_url"),
    Ferramenta("trello.listar_cartoes", "Cartoes abertos de um quadro permitido do Trello.", EntTrelloCartoes,
               lambda e, c: c.integracao("trello", "listar_cartoes", e.model_dump(exclude_none=True)), integracao="trello"),
    Ferramenta("notion.consultar_base", "Paginas de uma base permitida do Notion (titulos e datas).", EntNotion,
               lambda e, c: c.integracao("notion", "consultar_base", e.model_dump(exclude_none=True)), integracao="notion"),
    Ferramenta("google_agenda.eventos", "Eventos de um calendario permitido do Google Agenda (titulo e horario).", EntGoogleAgenda,
               lambda e, c: c.integracao("google_agenda", "eventos", e.model_dump(exclude_none=True)), integracao="google_agenda"),
    Ferramenta("gmail.listar", "Ultimas mensagens de um rotulo permitido do Gmail (cabecalhos e trecho, enderecos mascarados).", EntGmail,
               lambda e, c: c.integracao("gmail", "listar", e.model_dump(exclude_none=True)), integracao="gmail"),
    Ferramenta("jira.propor_comentario", "PROPOE um comentario numa issue do Jira; so e enviado se o operador aprovar.", EntJiraComentar,
               lambda e, c: c.propor("jira", "comentar", e.model_dump()), risco="escrita_aprovada", integracao="jira"),
    Ferramenta("jira.propor_transicao", "PROPOE mudar o status de uma issue do Jira; so acontece se o operador aprovar.", EntJiraTransicao,
               lambda e, c: c.propor("jira", "transicionar", e.model_dump()), risco="escrita_aprovada", integracao="jira"),
    Ferramenta("github.propor_comentario", "PROPOE um comentario numa issue/PR do GitHub; so e enviado se o operador aprovar.", EntGhComentar,
               lambda e, c: c.propor("github", "comentar", e.model_dump()), risco="escrita_aprovada", integracao="github"),
    Ferramenta("trello.propor_cartao", "PROPOE criar um cartao no Trello; so e criado se o operador aprovar.", EntTrelloCartao,
               lambda e, c: c.propor("trello", "criar_cartao", e.model_dump()), risco="escrita_aprovada", integracao="trello"),
    Ferramenta("web.buscar", "Busca na web (titulo, endereco e trecho) para achar documentacao, boas praticas e bugs conhecidos.", EntBuscaWeb,
               lambda e, c: c.integracao("busca_web", "buscar", e.model_dump(exclude_none=True)), integracao="busca_web"),
    Ferramenta("web.ler_pagina", "Texto de uma pagina que veio de web.buscar (ou de dominio liberado), sem scripts, limitado.", EntLerPagina,
               lambda e, c: c.integracao("busca_web", "ler_pagina", e.model_dump()), integracao="busca_web"),
    Ferramenta("env.verificar", "Valida um .env sem revelar valores: existe/vazia/formato/igual-a, e o que falta vs .env.example.", EntEnv,
               _env, True),
    Ferramenta("testes.resumir_saida", "Veredito e causa das falhas a partir da saida do pytest.", EntPytest,
               lambda e, c: resumir_pytest(e.texto, e.limite)),
    Ferramenta("git.diff_analisar", "Arquivos, areas e riscos de um diff unificado.", EntTexto,
               lambda e, c: resumir_diff(e.texto)),
    Ferramenta("logs.agrupar_falhas", "Erros de um log agrupados por assinatura.", EntLogs,
               lambda e, c: agrupar_falhas(e.texto, e.limite)),
    Ferramenta("dados.converter", "Converte json/jsonl/csv/md (tabela) de forma exata.", EntConverter,
               lambda e, c: converter(e.texto, e.de, e.para, e.delimitador, e.neutralizar_formulas)),
    Ferramenta("tokens.orcar", "Quais trechos cabem num orcamento de tokens (estimado).", EntOrcar,
               lambda e, c: orcar_tokens([i.model_dump() for i in e.itens], e.orcamento, e.teto_item)),
)


@dataclass
class Catalogo:
    raizes: tuple[Path, ...] = ()
    integracoes: Any = None
    acoes: Any = None  # AcoesExternasServico: as ferramentas *.propor_* so criam propostas
    politica: Callable[[], PoliticaPastas] | None = None  # preferencias do usuario (ativa/permitidas/proibidas); sem ela, usa `raizes`
    ferramentas: dict[str, Ferramenta] = field(default_factory=lambda: {f.id: f for f in FERRAMENTAS})
    _uso: dict[str, _Uso] = field(default_factory=dict)
    _mu: threading.Lock = field(default_factory=threading.Lock)

    def listar(self) -> list[dict[str, Any]]:
        return [
            {
                "id": f.id, "descricao": f.descricao, "risco": f.risco, "fallback": f.fallback,
                "usa_arquivos": f.usa_arquivos, "integracao": f.integracao,
                "disponivel": self._disponivel(f),
                "entrada": f.entrada.model_json_schema(),
            }
            for f in self.ferramentas.values()
        ]

    def _politica(self) -> PoliticaPastas:
        if self.politica is not None:
            return self.politica()
        return PoliticaPastas(ativa=bool(self.raizes), permitidas=self.raizes)

    def _disponivel(self, f: Ferramenta) -> bool:
        if f.integracao:
            if self.integracoes is None or not self.integracoes.pronta(f.integracao):
                return False
            if f.risco == "escrita_aprovada":  # propostas so aparecem com a escrita ligada E o servico de acoes presente
                return self.acoes is not None and bool(self.integracoes.estado(f.integracao)["configuracao"].get("permitir_escrita"))
            return True
        pol = self._politica()
        return (pol.ativa and bool(pol.permitidas)) or not f.usa_arquivos

    def estatisticas(self) -> dict[str, dict[str, Any]]:
        with self._mu:
            return {
                k: {"chamadas": u.chamadas, "erros": u.erros, "fallbacks": u.fallbacks,
                    "tokens_origem": u.tokens_origem, "tokens_resumo": u.tokens_resumo,
                    "ms_medio": round(u.ms / u.chamadas, 2) if u.chamadas else 0.0}
                for k, u in sorted(self._uso.items())
            }

    def _registrar(self, id_: str, ms: float, r: ResultadoFerramenta | None, fallback: bool = False) -> None:
        with self._mu:
            u = self._uso.setdefault(id_, _Uso())
            u.chamadas += 1
            u.ms += ms
            u.fallbacks += int(fallback)
            if r is None:
                u.erros += 1
            else:
                u.tokens_origem += r.tokens_origem
                u.tokens_resumo += r.tokens_resumo

    def executar(self, id_: str, entrada: dict[str, Any]) -> dict[str, Any]:
        f = self.ferramentas.get(id_)
        if f is None:
            raise NaoEncontrado(f"ferramenta {id_!r} nao existe")
        try:
            dados = f.entrada.model_validate(entrada)
        except ValidationError as e:
            raise ValidacaoDominio("entrada invalida: " + "; ".join(
                f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:5])) from e
        pol = self._politica()
        if f.id == "email.ler_mbox" and pol.mascarar_emails:  # privacidade: o agente nao consegue pedir enderecos completos
            dados = dados.model_copy(update={"mascarar_enderecos": True})
        ctx = Contexto(pol.permitidas if pol.ativa else (), self.integracoes, self.acoes)
        usada, de_fallback = f, None
        while True:
            ini = time.perf_counter()
            try:
                with aplicar(pol):
                    r = usada.rodar(dados if usada is f else usada.entrada(**_compat(dados)), ctx)
            except SemResultado:
                self._registrar(usada.id, (time.perf_counter() - ini) * 1000, None)
                alvo = self.ferramentas.get(usada.fallback or "")
                if alvo is None:
                    raise ValidacaoDominio("a ferramenta nao produziu resultado") from None
                de_fallback, usada = usada.id, alvo
                continue
            except ErroDominio:
                self._registrar(usada.id, (time.perf_counter() - ini) * 1000, None)
                raise
            except Exception as e:  # noqa: BLE001 - nunca vazar detalhe interno ao agente
                self._registrar(usada.id, (time.perf_counter() - ini) * 1000, None)
                log.exception("ferramenta falhou", extra={"ferramenta": usada.id})
                raise FerramentaFalhou(f"falha interna em {usada.id} ({type(e).__name__})") from e
            self._registrar(usada.id, (time.perf_counter() - ini) * 1000, r, fallback=de_fallback is not None)
            saida = r.model_dump()
            saida["reducao"] = round(r.reducao, 4)
            if de_fallback:
                saida["fallback_de"] = de_fallback
                saida["avisos"] = [*saida["avisos"], f"{de_fallback} sem resultado; usado {usada.id}"]
            return saida


def _compat(dados: BaseModel) -> dict[str, Any]:
    """Entrada do fallback: aproveita os campos que a ferramenta original e a de fallback compartilham."""
    return dados.model_dump()
