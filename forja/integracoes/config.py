"""Configuracao de uma integracao de rede. Guarda SO o que nao e segredo: o NOME das variaveis de ambiente, nunca o valor."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from forja.integracoes import ambiente

Texto = Annotated[str, StringConstraints(max_length=300)]


class ConfigIntegracao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ativo: bool = False  # nasce desligada: a funcionalidade existe, mas nada acontece sem o operador ligar
    base_url: Texto = ""
    versao_api: Literal["", "2", "3"] = ""
    provedor: Literal["", "brave", "searxng"] = ""  # so busca web
    modo_auth: Literal["", "basic", "bearer"] = ""
    variavel_usuario: Texto = ""
    variavel_token: Texto = ""
    variavel_url: Texto = ""
    variavel_segredo: Texto = ""  # 2o segredo (ex.: client secret do OAuth do Google)
    permitir_escrita: bool = False  # acoes de escrita (comentar, criar...) so com isto ligado E aprovacao por acao
    host_permitido: Texto = ""
    itens_permitidos: list[Annotated[str, StringConstraints(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=50)
    permitir_rede_privada: bool = False
    limite_por_minuto: int = Field(30, ge=1, le=120)
    limite_resultados: int = Field(20, ge=1, le=50)

    @model_validator(mode="after")
    def _sem_segredo_nem_variavel_arbitraria(self) -> ConfigIntegracao:
        from forja.ferramentas.segredos import suspeita  # import tardio: evita ciclo catalogo <-> integracoes

        for nome in ("variavel_usuario", "variavel_token", "variavel_url", "variavel_segredo"):
            valor = getattr(self, nome)
            if valor and not ambiente.nome_valido(valor):
                raise ValueError(f"{nome}: informe o NOME de uma variavel de ambiente no formato {ambiente.PREFIXO}NOME "
                                 "(o valor do segredo fica no ambiente/.env, nunca aqui)")
        for nome, valor in self.model_dump().items():
            textos = valor if isinstance(valor, list) else [valor]
            if any(isinstance(t, str) and t and suspeita(f"{nome} = '{t}'") for t in textos):
                raise ValueError(f"{nome}: o valor parece uma credencial. Guarde-a no ambiente e informe so o nome da variavel")
        return self
