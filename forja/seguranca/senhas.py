"""Senhas das contas locais: politica minima, hash scrypt com sal e verificacao em tempo constante. So biblioteca padrao.

Formato guardado: `scrypt$n$r$p$<sal b64>$<hash b64>`. Parametros dentro do valor: aumentar o custo no futuro nao invalida
as senhas antigas (elas sao reconferidas com os proprios parametros).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

from forja.dominio.erros import ValidacaoDominio

N, R, P, DKLEN = 2**14, 8, 1, 32  # ~16 MB e ~50 ms por verificacao: caro para forca bruta, imperceptivel para o usuario
MIN_SENHA, MAX_SENHA = 8, 200
_NOME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
# senhas mais comuns em vazamentos publicos (amostra pequena; o bloqueio por tentativas cobre o resto)
_COMUNS = frozenset({"12345678", "123456789", "1234567890", "password", "password1", "senha123", "senha1234", "qwerty123",
                     "11111111", "00000000", "abc12345", "iloveyou", "admin123", "administrador", "forja123", "mudar123"})


def normalizar_nome(nome: str) -> str:
    n = (nome or "").strip().casefold()
    if not _NOME.match(n):
        raise ValidacaoDominio("Usuário: de 3 a 32 caracteres (letras minúsculas, números, ponto, hífen ou sublinhado).")
    return n


def validar_senha(senha: str, nome: str = "") -> str:
    if not isinstance(senha, str) or not (MIN_SENHA <= len(senha) <= MAX_SENHA):
        raise ValidacaoDominio(f"Senha: de {MIN_SENHA} a {MAX_SENHA} caracteres.")
    if senha.casefold() in _COMUNS or len(set(senha)) < 4:
        raise ValidacaoDominio("Senha muito fácil de adivinhar; use uma frase ou combine palavras.")
    if nome and nome.casefold() in senha.casefold():
        raise ValidacaoDominio("A senha não pode conter o nome de usuário.")
    return senha


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def gerar_hash(senha: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(senha.encode("utf-8"), salt=sal, n=N, r=R, p=P, dklen=DKLEN, maxmem=64 * 1024 * 1024)
    return f"scrypt${N}${R}${P}${_b64(sal)}${_b64(h)}"


def conferir(senha: str, guardado: str) -> bool:
    try:
        alg, n, r, p, sal, h = guardado.split("$")
        if alg != "scrypt":
            return False
        calc = hashlib.scrypt(senha.encode("utf-8"), salt=base64.b64decode(sal), n=int(n), r=int(r), p=int(p),
                              dklen=len(base64.b64decode(h)), maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


HASH_FICTICIO = gerar_hash(secrets.token_urlsafe(16))  # usuario inexistente custa o mesmo tempo (nao revela quem existe)
