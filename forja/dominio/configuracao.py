"""Configuracao do orquestrador por parte do sistema (modelo e esforco de IA de cada parte).

So entra aqui o que tem EFEITO real. Partes deterministicas (busca, contexto) nao usam modelo e recusam um.

Hierarquia de agentes (ADR-020): quem PLANEJA e REVISA usa o modelo mais forte; quem EXECUTA usa o melhor custo-beneficio
em codigo; trabalho somente-leitura, triagem e tarefas simples usam o modelo rapido e barato. Os padroes abaixo vieram do
catalogo real da conta Kiro (custo relativo em creditos) cruzado com benchmarks publicos de nov/2026; cada padrao tem
reserva `auto` para nunca bloquear numa conta que nao ofereca o modelo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ModeloId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$")]
Esforco = Literal["", "low", "medium", "high", "xhigh", "max"]  # effortLevel da sessao ACP (vazio = padrao)


@dataclass(frozen=True)
class Parte:
    id: str
    rotulo: str
    descricao: str
    usa_modelo: bool
    papel: str = ""  # posicao na hierarquia (mostrada na tela)


PARTES: tuple[Parte, ...] = (
    Parte("rapida", "Tarefas simples", "Perguntas curtas, análises pontuais e documentação pequena: resposta rápida e barata.", True,
          "operário rápido (somente leitura)"),
    Parte("execucao", "Execucao de tarefas", "Agente Kiro que executa e conversa sobre cada tarefa de porte normal.", True,
          "executor (implementa e verifica)"),
    Parte("planejamento", "Planejamento de tarefas complexas", "Turno de plano/pesquisa antes de executar tarefas complexas.", True,
          "planejador (mestre)"),
    Parte("revisao", "Revisao do esquema", "Agente que reavalia a arquitetura e sugere melhorias.", True, "revisor (mestre)"),
    Parte("estudo", "Estudo e alimentação do segundo cérebro", "Resume pastas e pesquisas em notas candidatas organizadas por tópico.",
          True, "pesquisador/resumidor (somente leitura)"),
    Parte("coordenacao", "Master e sub-masters", "Conversa com você, entende o pedido e decide quais tarefas e sub-masters criar.",
          True, "coordenador (não executa)"),
    Parte("status", "Resumos de status", "Resume o que os agentes fizeram em frases curtas para você (só em marcos, em lote).",
          True, "relator (barato)"),
    Parte("contexto", "Contexto e memoria", "Busca lexical e montagem de contexto: deterministico, sem modelo.", False, "determinístico"),
    Parte("ferramentas", "Ferramentas N0", "Resumos, mapas e varreduras: deterministicos, sem modelo.", False, "determinístico"),
)
PARTES_POR_ID = {p.id: p for p in PARTES}


class ParteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    modelo: ModeloId | Literal[""] = Field("", description="Vazio = padrao da Forja para a parte (ou APP_KIRO_MODEL).")
    esforco: Esforco = ""
    # Fallback EXPLICITO e ordenado: se o modelo escolhido nao estiver na conta, tenta estes, em ordem, e registra qual foi
    # usado. Sem lista, continua a falha fechada (nunca troca de modelo em silencio).
    alternativas: list[ModeloId] = Field(default_factory=list, max_length=3)


# Padroes da Forja (catalogo kiro-cli 3.1.0, nov/2026: haiku-5.5 0,06x | sonnet-5.5 1,30x | opus-5.5 2,00x | auto 1,00x).
PADROES: dict[str, ParteConfig] = {
    "rapida": ParteConfig(modelo="claude-haiku-5.5", esforco="medium", alternativas=["claude-haiku-4.5", "auto"]),
    "execucao": ParteConfig(modelo="claude-sonnet-5.5", esforco="medium", alternativas=["claude-sonnet-5", "auto"]),
    "planejamento": ParteConfig(modelo="claude-opus-5.5", esforco="high", alternativas=["claude-sonnet-5.5", "auto"]),
    "revisao": ParteConfig(modelo="claude-opus-5.5", esforco="high", alternativas=["claude-sonnet-5.5", "auto"]),
    "estudo": ParteConfig(modelo="claude-haiku-5.5", esforco="medium", alternativas=["claude-sonnet-5.5", "auto"]),
    # master: decide e distribui (texto curto + acoes tipadas), sem ferramentas: sonnet basta e custa menos que o opus
    "coordenacao": ParteConfig(modelo="claude-sonnet-5.5", esforco="medium", alternativas=["claude-sonnet-5", "auto"]),
    "status": ParteConfig(modelo="claude-haiku-5.5", esforco="low", alternativas=["claude-haiku-4.5", "auto"]),
}


class ConfiguracaoSistema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    partes: dict[str, ParteConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _partes_validas(self) -> ConfiguracaoSistema:
        for pid, cfg in self.partes.items():
            parte = PARTES_POR_ID.get(pid)
            if parte is None:
                raise ValueError(f"parte desconhecida: {pid!r}")
            if (cfg.modelo or cfg.esforco or cfg.alternativas) and not parte.usa_modelo:
                raise ValueError(f"a parte {pid!r} e deterministica e nao usa modelo nem esforco")
        return self


class SalvarConfiguracaoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    configuracao: ConfiguracaoSistema
