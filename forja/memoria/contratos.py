"""Contratos de entrada da memoria (Pydantic v2)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from forja.dominio.contratos import _ID_RE, padrao_recurso_valido
from forja.memoria.modelo import ARESTAS, ESTADOS_ARESTA, NOS, EstadoMemoria, TipoMemoria, validar_namespace

Texto = Annotated[str, Field(min_length=1, max_length=200)]
Id = Annotated[str, Field(pattern=_ID_RE.pattern)]


class _Estrito(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FonteIn(_Estrito):
    tipo: Literal["git", "documento", "teste", "manual", "execucao", "adr"] = "manual"
    repositorio: Annotated[str, Field(max_length=200)] = ""
    commit: Annotated[str, Field(max_length=64)] = ""
    caminho: Annotated[str, Field(max_length=500)] = ""
    hash: Annotated[str, Field(max_length=64)] = ""

    @field_validator("caminho")
    @classmethod
    def _caminho_relativo(cls, v: str) -> str:
        if v and not padrao_recurso_valido(v):
            raise ValueError("caminho de fonte deve ser relativo ao repositorio (sem .., drive ou absoluto)")
        return v.replace("\\", "/")


class AfirmacaoIn(_Estrito):
    """Fato estruturado, para detectar contradicao entre memorias do mesmo namespace."""

    sujeito: Annotated[str, Field(min_length=1, max_length=200)]
    valor: Annotated[str, Field(min_length=1, max_length=500)]


class MemoriaIn(_Estrito):
    tipo: TipoMemoria
    titulo: Texto
    resumo: Annotated[str, Field(max_length=2000)] = ""
    conteudo: Annotated[str, Field(max_length=100_000)] = ""
    namespace: str
    fonte: FonteIn = Field(default_factory=FonteIn)
    precondicoes: list[Texto] = Field(default_factory=list, max_length=30)
    tags: list[Annotated[str, Field(min_length=1, max_length=50)]] = Field(default_factory=list, max_length=30)
    refs: list[Texto] = Field(default_factory=list, max_length=50)
    afirma: AfirmacaoIn | None = None
    confianca: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    retencao_dias: Annotated[int, Field(ge=1, le=3650)] | None = None

    @field_validator("namespace")
    @classmethod
    def _ns(cls, v: str) -> str:
        return validar_namespace(v)


class MemoriaAtualizaIn(_Estrito):
    expected_version: int = Field(ge=1)
    titulo: Texto | None = None
    resumo: Annotated[str, Field(max_length=2000)] | None = None
    conteudo: Annotated[str, Field(max_length=100_000)] | None = None
    tags: list[Annotated[str, Field(min_length=1, max_length=50)]] | None = Field(default=None, max_length=30)
    afirma: AfirmacaoIn | None = None
    motivo: Annotated[str, Field(max_length=1000)] = ""


class TransicaoMemoriaIn(_Estrito):
    para: EstadoMemoria
    expected_version: int = Field(ge=1)
    motivo: Annotated[str, Field(max_length=1000)] = ""


class ValidarIn(_Estrito):
    expected_version: int = Field(ge=1)
    validado_por: Texto  # quem/o que validou: ex. 'teste_integracao_local', 'revisao_humana'


class VincularEvidenciaIn(_Estrito):
    evidencia_id: Id


class ResolverConflitoIn(_Estrito):
    vencedora_id: Id
    perdedoras_ids: list[Id] = Field(min_length=1, max_length=20)
    motivo: Annotated[str, Field(min_length=3, max_length=1000)]


class RevalidarIn(_Estrito):
    expected_version: int = Field(ge=1)
    nova_fonte_hash: Annotated[str, Field(max_length=64)] = ""


class IngerirIn(_Estrito):
    namespace: str
    raiz: Annotated[str, Field(min_length=1, max_length=500)]
    repositorio: Texto
    commit_sha: Annotated[str, Field(max_length=64)] = ""

    @field_validator("namespace")
    @classmethod
    def _ns(cls, v: str) -> str:
        return validar_namespace(v)


class NoIn(_Estrito):
    tipo: str
    nome: Texto
    namespace: str
    props: dict[str, Any] = Field(default_factory=dict)
    fonte: FonteIn = Field(default_factory=FonteIn)

    @field_validator("tipo")
    @classmethod
    def _tipo(cls, v: str) -> str:
        if v not in NOS:
            raise ValueError(f"tipo de no fora da ontologia: {v!r}")
        return v

    @field_validator("namespace")
    @classmethod
    def _ns(cls, v: str) -> str:
        return validar_namespace(v)


class ArestaIn(_Estrito):
    origem: Id
    destino: Id
    tipo: str
    namespace: str
    fonte: FonteIn = Field(default_factory=FonteIn)
    estado: str = "candidato"
    valido_de: str | None = None
    valido_ate: str | None = None

    @field_validator("tipo")
    @classmethod
    def _tipo(cls, v: str) -> str:
        if v not in ARESTAS:
            raise ValueError(f"tipo de aresta fora da ontologia: {v!r}")
        return v

    @field_validator("estado")
    @classmethod
    def _estado(cls, v: str) -> str:
        if v not in ESTADOS_ARESTA:
            raise ValueError(f"estado de aresta invalido: {v!r}")
        return v

    @field_validator("namespace")
    @classmethod
    def _ns(cls, v: str) -> str:
        return validar_namespace(v)
