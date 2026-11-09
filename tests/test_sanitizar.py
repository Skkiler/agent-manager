"""Sanitizacao de payloads/logs: redige segredos, preserva contadores de consumo (regressao: tokens_* virava [REDACTED])."""

from __future__ import annotations

import pytest

from forja.observabilidade.sanitizar import REDACTED, sanitizar, sanitizar_texto


@pytest.mark.parametrize("chave", ["tokens_input", "tokens_output", "max_tokens", "total_tokens", "max_tokens_item", "tokens"])
def test_contadores_de_consumo_numericos_nao_sao_redigidos(chave):
    assert sanitizar({chave: 123})[chave] == 123
    assert sanitizar({chave: None})[chave] is None


def test_consumo_aninhado_do_resultado_do_agente_sobrevive():
    r = sanitizar({"consumo": {"tokens_input": 840, "tokens_output": 310, "fonte": "estimado", "chamadas_modelo": 2}})
    assert r["consumo"] == {"tokens_input": 840, "tokens_output": 310, "fonte": "estimado", "chamadas_modelo": 2}


@pytest.mark.parametrize("chave", ["token", "api_token", "access_token", "password", "senha", "secret", "Authorization",
                                   "cookie", "api_key", "private_key", "credential"])
def test_credenciais_continuam_redigidas(chave):
    assert sanitizar({chave: "valor-secreto"})[chave] == REDACTED


def test_chave_de_contador_com_valor_textual_continua_redigida():
    """'tokens_input' so escapa da redacao quando o valor e numerico: texto numa chave assim e suspeito."""
    assert sanitizar({"tokens_input": "eyJhbGciOiJIUzI1NiJ9.segredo"})["tokens_input"] == REDACTED


def test_segredos_em_valores_de_texto_sao_redigidos_e_truncados():
    assert "abc123" not in sanitizar_texto("falha com token=abc123 na chamada")
    assert sanitizar_texto("x" * 5000).endswith("[truncado]")


def test_estruturas_profundas_e_listas_grandes_sao_limitadas():
    profundo: dict = {}
    atual = profundo
    for _ in range(20):
        atual["n"] = {}
        atual = atual["n"]
    assert "profundidade-limitada" in str(sanitizar(profundo))
    assert len(sanitizar(list(range(1000)))) == 200
