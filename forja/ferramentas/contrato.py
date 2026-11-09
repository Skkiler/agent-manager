"""Contrato comum das ferramentas N0. Somente leitura, sem rede, sem shell; a saida e dado nao confiavel."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from forja.memoria.saneamento import estimar_tokens
from forja.observabilidade.sanitizar import redigir_segredos

VERSAO = "1.0.0"


class ResultadoFerramenta(BaseModel):
    ferramenta: str
    versao: str = VERSAO
    risco: str = "leitura"
    resumo: str = Field(description="Texto compacto para o prompt do agente (segredos redigidos).")
    dados: dict[str, Any] = Field(default_factory=dict, description="Estrutura tipada com proveniencia.")
    tokens_origem: int = Field(description="Tokens ESTIMADOS (~4 car./token) do material bruto que seria lido.")
    tokens_resumo: int = Field(description="Tokens ESTIMADOS do `resumo`.")
    truncado: bool = False
    avisos: list[str] = Field(default_factory=list)
    conteudo_nao_confiavel: bool = True

    @property
    def reducao(self) -> float:
        """Fracao economizada (0..1) frente ao material bruto. Estimada, nao medida no provedor."""
        return 0.0 if self.tokens_origem <= 0 else max(0.0, 1 - self.tokens_resumo / self.tokens_origem)


def tokens_de_bytes(n: int) -> int:
    """Estimativa (~4 bytes/token) sem materializar o texto."""
    return max(0, (n + 3) // 4)


def montar(ferramenta: str, bruto: str, resumo: str, dados: dict[str, Any], truncado: bool = False,
           avisos: list[str] | None = None, tokens_origem: int | None = None) -> ResultadoFerramenta:
    """`tokens_origem` explicito serve a ferramentas que varrem muito material sem carrega-lo em `bruto`."""
    resumo = redigir_segredos(resumo)
    return ResultadoFerramenta(
        ferramenta=ferramenta,
        resumo=resumo,
        dados=dados,
        tokens_origem=estimar_tokens(bruto) if tokens_origem is None else tokens_origem,
        tokens_resumo=estimar_tokens(resumo),
        truncado=truncado,
        avisos=avisos or [],
    )
