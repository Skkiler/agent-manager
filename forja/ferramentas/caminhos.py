"""Unico ponto que decide se uma ferramenta pode tocar num caminho. Toda ferramenta de arquivo passa por aqui."""

from __future__ import annotations

import os
from pathlib import Path

from forja.dominio.erros import NaoEncontrado, ValidacaoDominio
from forja.seguranca.acoes import caminho_sensivel
from forja.seguranca.pastas import proibido


def resolver_dentro(raiz: Path, caminho: str, *, diretorio: bool = False) -> Path:
    """Devolve o caminho real de `caminho` (relativo a `raiz`) ou levanta erro de dominio.

    Recusa: vazio/NUL, arquivo sensivel (.env, chaves...), link simbolico, fora da raiz e tipo errado (arquivo x pasta)."""
    if not caminho or "\x00" in caminho:
        raise ValidacaoDominio("caminho invalido")
    if caminho_sensivel(caminho):
        raise ValidacaoDominio("arquivo sensivel nao pode ser lido por esta ferramenta")
    base = raiz.resolve()
    alvo = base / caminho
    try:  # contencao LEXICA primeiro: evita revelar (404 x 422) se existe algo fora da raiz
        candidato = Path(os.path.normpath(alvo))
        candidato.relative_to(base)
    except ValueError as e:
        raise ValidacaoDominio("caminho fora da raiz autorizada") from e
    if proibido(candidato):  # pasta proibida/protegida: mesma resposta de "fora da raiz", exista ou nao
        raise ValidacaoDominio("caminho fora da raiz autorizada")
    if alvo.is_symlink():
        raise ValidacaoDominio("links simbolicos nao sao seguidos")
    try:
        real = alvo.resolve(strict=True)
        real.relative_to(base)
    except FileNotFoundError as e:
        raise NaoEncontrado("caminho nao encontrado") from e
    except (ValueError, OSError) as e:
        raise ValidacaoDominio("caminho fora da raiz autorizada") from e
    if proibido(real):  # symlink/juncao que desvia para uma pasta proibida
        raise ValidacaoDominio("caminho fora da raiz autorizada")
    if diretorio and not real.is_dir():
        raise ValidacaoDominio("era esperado um diretorio")
    if not diretorio and not real.is_file():
        raise ValidacaoDominio("era esperado um arquivo")
    return real
