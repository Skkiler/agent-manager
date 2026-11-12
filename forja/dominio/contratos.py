"""Contratos tipados de entrada/saida (Pydantic v2). Nada aqui depende de Kiro."""

from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from forja.dominio.estados import EstadoTarefa

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
Texto = Annotated[str, Field(min_length=1, max_length=200)]
TextoLongo = Annotated[str, Field(max_length=4000)]


class _Estrito(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def padrao_recurso_valido(p: str) -> bool:
    """Padrao relativo ao workspace: sem absoluto, drive, '..', '~', NUL ou barra invertida inicial."""
    if not p or len(p) > 260 or "\x00" in p or p.startswith(("/", "\\", "~")):
        return False
    if re.match(r"^[A-Za-z]:", p):
        return False
    partes = re.split(r"[\\/]", p)
    return ".." not in partes


class Orcamento(_Estrito):
    max_chamadas_modelo: int = Field(default=10, ge=0, le=1000)
    max_tentativas: int = Field(default=2, ge=1, le=20)
    max_duracao_segundos: int = Field(default=1200, ge=1, le=86400)


class Recursos(_Estrito):
    leitura: list[str] = Field(default_factory=list, max_length=100)
    escrita: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("leitura", "escrita")
    @classmethod
    def _padroes(cls, v: list[str]) -> list[str]:
        for p in v:
            if not padrao_recurso_valido(p):
                raise ValueError(f"padrao de recurso invalido: {p!r}")
        return v


class Politicas(_Estrito):
    sandbox: Literal["nenhum", "worktree"] = "nenhum"
    exige_revisao: bool = False
    exige_aprovacao: bool = False
    # Contexto recuperado da memoria no prompt: 'auto' (so se houver acerto relevante) ou 'nenhum' (custo zero).
    contexto: Literal["auto", "nenhum"] = "auto"
    contexto_max_tokens: int | None = Field(default=None, ge=50, le=20_000)


class ProjetoIn(_Estrito):
    nome: Texto
    descricao: TextoLongo = ""


class ObjetivoIn(_Estrito):
    projeto_id: Annotated[str, Field(pattern=_ID_RE.pattern)]
    titulo: Texto
    descricao: TextoLongo = ""
    prioridade: int = Field(default=3, ge=1, le=5)
    criterios_sucesso: list[Texto] = Field(default_factory=list, max_length=50)
    orcamento: Orcamento = Field(default_factory=Orcamento)


class TarefaIn(_Estrito):
    objetivo_id: Annotated[str, Field(pattern=_ID_RE.pattern)]
    titulo: Texto
    descricao: TextoLongo = ""
    criterios_aceite: list[Texto] = Field(min_length=1, max_length=50)
    dependencias: list[Annotated[str, Field(pattern=_ID_RE.pattern)]] = Field(default_factory=list, max_length=50)
    especialidade: Texto = "geral"
    modo: Literal["analise", "alteracao_codigo", "verificacao", "documentacao", "estudo"] = "analise"
    recursos: Recursos = Field(default_factory=Recursos)
    orcamento: Orcamento = Field(default_factory=Orcamento)
    politicas: Politicas = Field(default_factory=Politicas)
    entrada: dict[str, Any] = Field(default_factory=dict)
    contexto_refs: list[Texto] = Field(default_factory=list, max_length=50)

    @field_validator("entrada")
    @classmethod
    def _entrada_pequena(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v, default=str)) > 16_000:
            raise ValueError("entrada excede 16 KB")
        return v


class TransicaoIn(_Estrito):
    para: EstadoTarefa
    expected_version: int = Field(ge=1)
    motivo: TextoLongo = ""


class DecisaoAprovacaoIn(_Estrito):
    """Decisao sobre UM grupo de acoes. `itens_aprovados=None` + aprovada = aprova todos os itens do grupo."""

    decisao: Literal["aprovada", "negada"]
    justificativa: TextoLongo = ""
    itens_aprovados: list[Annotated[str, Field(max_length=200)]] | None = Field(default=None, max_length=50)
    adendo: TextoLongo = ""  # orientacao livre do operador, registrada e entregue ao agente
    lembrar_na_execucao: bool = False  # reaproveita a aprovacao para acoes identicas ate o fim desta execucao


class DecisaoLoteIn(_Estrito):
    """Uma unica decisao aplicada a varios pedidos de aprovacao de uma vez."""

    ids: list[Annotated[str, Field(pattern=_ID_RE.pattern)]] = Field(min_length=1, max_length=20)
    decisao: Literal["aprovada", "negada"]
    adendo: TextoLongo = ""
    lembrar_na_execucao: bool = False


# ---- Contrato de resultado/handoff (secao 6.4) ----


class ConsumoMedicao(_Estrito):
    tokens_input: int | None = None
    tokens_output: int | None = None
    latencia_ms: int | None = None
    chamadas_modelo: int = Field(default=0, ge=0)
    # Nunca inventar consumo: 'provedor' | 'estimado' | 'indisponivel' | 'simulado'
    fonte: Literal["provedor", "estimado", "indisponivel", "simulado"] = "indisponivel"


class ArtefatoSaida(_Estrito):
    nome: Texto
    tipo: Literal["texto", "json"] = "texto"
    conteudo: str = Field(max_length=1_000_000)


class EvidenciaSaida(_Estrito):
    tipo: Texto
    resumo: TextoLongo
    simulada: bool = False
    artefato: str | None = None  # nome de um ArtefatoSaida do mesmo resultado


class MensagemSaida(_Estrito):
    """Uma secao da resposta do agente, ja organizada como conversa (entendimento, resposta, decisoes...)."""

    tipo: Annotated[str, Field(min_length=1, max_length=32)]
    conteudo: Annotated[str, Field(max_length=100_000)]
    dados: dict[str, Any] | None = None


class ConversaIn(_Estrito):
    """Resposta livre do desenvolvedor na conversa de uma tarefa (UMA resposta cobre todas as decisoes pendentes)."""

    conteudo: Annotated[str, Field(min_length=1, max_length=8000)]
    retomar: bool = True  # se a tarefa estiver aguardando decisoes, retoma a execucao com esta resposta


class ResultadoAgente(_Estrito):
    estado: Literal["concluida", "falhou", "bloqueada", "pausada", "cancelada"]
    resumo: TextoLongo
    agente_id: Texto
    mock: bool = False
    artefatos: list[ArtefatoSaida] = Field(default_factory=list)
    evidencias: list[EvidenciaSaida] = Field(default_factory=list)
    hipoteses: list[str] = Field(default_factory=list)
    pendencias: list[str] = Field(default_factory=list)
    mensagens: list[MensagemSaida] = Field(default_factory=list)
    consumo: ConsumoMedicao = Field(default_factory=ConsumoMedicao)
    proximo_passo: str | None = None
