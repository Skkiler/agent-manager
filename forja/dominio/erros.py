"""Excecoes de dominio (mapeadas para HTTP somente na camada de API)."""

from __future__ import annotations


class ErroDominio(Exception):
    codigo = "erro_dominio"
    status = 400

    def __init__(self, mensagem: str) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem


class NaoEncontrado(ErroDominio):
    codigo = "nao_encontrado"
    status = 404


class Conflito(ErroDominio):
    codigo = "conflito"
    status = 409


class ConflitoVersao(Conflito):
    codigo = "conflito_versao"


class TransicaoInvalida(Conflito):
    codigo = "transicao_invalida"


class TransicaoReservada(Conflito):
    codigo = "transicao_reservada"


class CredenciaisInvalidas(ErroDominio):
    codigo, status = "credenciais_invalidas", 401


class AcessoBloqueado(ErroDominio):
    codigo, status = "acesso_bloqueado", 429

    def __init__(self, mensagem: str, tentar_em_s: int) -> None:
        super().__init__(mensagem)
        self.tentar_em_s = tentar_em_s


class OrcamentoExcedido(Conflito):
    codigo = "orcamento_excedido"


class LockIndisponivel(Conflito):
    codigo = "recurso_bloqueado"


class ValidacaoDominio(ErroDominio):
    codigo = "validacao"
    status = 422


class IdempotenciaConflito(ValidacaoDominio):
    codigo = "idempotency_key_reutilizada"
