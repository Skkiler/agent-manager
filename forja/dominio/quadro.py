"""Contratos do quadro de comunicacao (blackboard). Mensagens sao dados tipados: malformada nunca vira comando."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

MAX_PAYLOAD = 4000
MASTER_E_OPERADOR = frozenset({"master", "operador"})

Origem = Annotated[str, StringConstraints(pattern=r"^(master|operador|sistema|agente:[a-z0-9_.-]{1,40})$")]
Destino = Annotated[str, StringConstraints(pattern=r"^(master|operador|todos|agente:[a-z0-9_.-]{1,40})$")]
Referencia = Annotated[
    str, StringConstraints(pattern=r"^(memoria|tarefa|execucao|artefato|evidencia|arquivo|nota):[\w./#:\-]{1,180}$")
]


class TipoMensagem(StrEnum):
    COMANDO = "comando"  # instrui; so master/operador
    EVENTO = "evento"  # fato ocorrido; pode ser difundido a "todos"
    APONTAMENTO = "apontamento"  # anotacao priorizada para o master acompanhar
    PERGUNTA = "pergunta"  # pede decisao ou informacao especifica
    RESULTADO = "resultado"  # entrega de um agente, com referencias a evidencias


class EstadoMensagem(StrEnum):
    PENDENTE = "pendente"
    ENTREGUE = "entregue"
    RESOLVIDA = "resolvida"
    EXPIRADA = "expirada"


class MensagemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origem: Origem
    destino: Destino
    tipo: TipoMensagem
    prioridade: int = Field(3, ge=1, le=5, description="1 = mais urgente")
    assunto: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    payload: dict[str, Any] = Field(default_factory=dict)
    referencias: list[Referencia] = Field(default_factory=list, max_length=20)
    tarefa_id: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = None
    expira_em_segundos: int | None = Field(None, ge=60, le=30 * 86400)
    dedup_key: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None

    @field_validator("payload")
    @classmethod
    def _payload_pequeno(cls, v: dict[str, Any]) -> dict[str, Any]:
        try:
            tamanho = len(json.dumps(v, ensure_ascii=False))
        except (TypeError, ValueError) as e:
            raise ValueError("payload precisa ser JSON serializavel") from e
        if tamanho > MAX_PAYLOAD:
            raise ValueError(f"payload acima de {MAX_PAYLOAD} caracteres: envie referencias, nao conteudo")
        return v

    @model_validator(mode="after")
    def _regras(self) -> MensagemIn:
        if self.origem == self.destino:
            raise ValueError("origem e destino nao podem ser iguais")
        if self.tipo == TipoMensagem.COMANDO and self.origem not in MASTER_E_OPERADOR:
            raise ValueError("comando so pode partir de master ou operador")
        if self.destino == "todos" and self.tipo not in (TipoMensagem.EVENTO, TipoMensagem.APONTAMENTO):
            raise ValueError("difusao (todos) e permitida apenas para evento e apontamento")
        if self.origem == "sistema" and self.tipo not in (TipoMensagem.EVENTO, TipoMensagem.APONTAMENTO):
            raise ValueError("sistema so publica evento ou apontamento")
        return self


class ResolverIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nota: Annotated[str, StringConstraints(max_length=1000)] = ""
