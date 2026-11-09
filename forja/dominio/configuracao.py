"""Configuracao do orquestrador por parte do sistema (modelo de IA de cada parte) e nivel de detalhe da interface.

So entra aqui o que tem EFEITO real. Partes deterministicas (busca, contexto) nao usam modelo e recusam um.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ModeloId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$")]
Esforco = Literal["", "low", "medium", "high", "xhigh", "max"]  # --effort do kiro-cli acp (vazio = padrao)


@dataclass(frozen=True)
class Parte:
    id: str
    rotulo: str
    descricao: str
    usa_modelo: bool


PARTES: tuple[Parte, ...] = (
    Parte("execucao", "Execucao de tarefas", "Agente Kiro que executa e conversa sobre cada tarefa.", True),
    Parte("revisao", "Revisao do esquema", "Agente que reavalia a arquitetura e sugere melhorias.", True),
    Parte("contexto", "Contexto e memoria", "Busca lexical e montagem de contexto: deterministico, sem modelo.", False),
    Parte("ferramentas", "Ferramentas N0", "Resumos, mapas e varreduras: deterministicos, sem modelo.", False),
)
PARTES_POR_ID = {p.id: p for p in PARTES}


class ParteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    modelo: ModeloId | Literal[""] = Field("", description="Vazio = padrao da conta/politica do Kiro.")
    esforco: Esforco = ""


class ConfiguracaoSistema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nivel_detalhe: Literal["simples", "avancado"] = "simples"
    partes: dict[str, ParteConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _partes_validas(self) -> ConfiguracaoSistema:
        for pid, cfg in self.partes.items():
            parte = PARTES_POR_ID.get(pid)
            if parte is None:
                raise ValueError(f"parte desconhecida: {pid!r}")
            if (cfg.modelo or cfg.esforco) and not parte.usa_modelo:
                raise ValueError(f"a parte {pid!r} e deterministica e nao usa modelo nem esforco")
        return self


class SalvarConfiguracaoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    configuracao: ConfiguracaoSistema
