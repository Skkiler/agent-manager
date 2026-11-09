"""Contrato do pedido de revisao do esquema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Escopo = Literal["arquitetura", "busca_e_memoria", "ferramentas", "interface", "seguranca", "custo_e_modelos"]


class SolicitarRevisaoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    escopo: list[Escopo] = Field(default_factory=lambda: ["arquitetura"], min_length=1, max_length=6)
    pesquisar_web: bool = False  # so pede ao agente; a pesquisa passa pelas aprovacoes por acao como qualquer ferramenta
    executar: bool = False  # False = cria e prepara a tarefa; True = tambem inicia (consome creditos do provedor)
