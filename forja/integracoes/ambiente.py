"""Segredos de integracao vivem no AMBIENTE (variavel de processo ou arquivo .env), nunca no banco, na API ou no Git.

A configuracao guarda apenas o NOME da variavel. Para que isso nao vire um jeito de ler variaveis arbitrarias do processo
(ex.: apontar para uma credencial de nuvem e envia-la a um host), so nomes com o prefixo `FORJA_INT_` sao aceitos.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import dotenv_values

PREFIXO = "FORJA_INT_"
_NOME = re.compile(r"^FORJA_INT_[A-Z0-9_]{1,50}$")
_arquivos: list[Path] = [Path(".env")]  # ordem de busca; o do usuario (fora do Git) vem primeiro, definido pelo app


def definir_arquivos(arquivos: list[Path]) -> None:
    _arquivos[:] = list(arquivos)


def nome_valido(nome: str) -> bool:
    return bool(_NOME.fullmatch(nome or ""))


def ler(nome: str, arquivo_env: Path | None = None) -> str | None:
    """Valor da variavel (processo primeiro, depois .env) ou None. NUNCA registre nem devolva este valor por API."""
    if not nome_valido(nome):
        return None
    valor = os.environ.get(nome)
    for arq in ([arquivo_env] if arquivo_env is not None else _arquivos) if valor is None else []:
        try:
            valor = dotenv_values(arq).get(nome)
        except OSError:
            valor = None
        if valor:
            break
    valor = (valor or "").strip()
    return valor or None


def presente(nome: str, arquivo_env: Path | None = None) -> bool:
    return ler(nome, arquivo_env) is not None
