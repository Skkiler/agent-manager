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
from forja.ferramentas.amostra import amostra_arquivo
from forja.ferramentas.contrato import ResultadoFerramenta
from forja.ferramentas.conversor import converter
from forja.ferramentas.diff import resumir_diff
from forja.ferramentas.esquema import inspecionar_sqlite
from forja.ferramentas.logs import agrupar_falhas
from forja.ferramentas.mapa import mapa_repositorio
from forja.ferramentas.orcamento import orcar_tokens
from forja.ferramentas.outline import outline_arquivo
from forja.ferramentas.segredos import varrer
from forja.ferramentas.testes import resumir_pytest

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
    ferramentas: dict[str, Ferramenta] = field(default_factory=lambda: {f.id: f for f in FERRAMENTAS})
    _uso: dict[str, _Uso] = field(default_factory=dict)
    _mu: threading.Lock = field(default_factory=threading.Lock)

    def listar(self) -> list[dict[str, Any]]:
        return [
            {
                "id": f.id, "descricao": f.descricao, "risco": f.risco, "fallback": f.fallback,
                "usa_arquivos": f.usa_arquivos, "disponivel": bool(self.raizes) or not f.usa_arquivos,
                "entrada": f.entrada.model_json_schema(),
            }
            for f in self.ferramentas.values()
        ]

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
        ctx = Contexto(self.raizes)
        usada, de_fallback = f, None
        while True:
            ini = time.perf_counter()
            try:
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
