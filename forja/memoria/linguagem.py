"""Linguagem da busca: radicais PT/EN, sinonimos tecnicos e stopwords. Puro e deterministico, sem modelo e sem rede.

Objetivo: perguntas em linguagem natural ("como logar no portal?") acharem documentos que dizem "autenticacao",
SEM embeddings. Cada termo vira um GRUPO de alternativas (o termo, seu radical com prefixo e sinonimos); os grupos sao
combinados com AND. Tudo e transparente: a resposta informa com o que cada termo foi expandido.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

STOPWORDS = frozenset(
    """
a o as os um uma uns umas de do da dos das em no na nos nas por para pra com sem sob sobre ate entre e ou mas que se
como qual quais quando onde porque ja ainda muito mais menos ao aos so tambem isso isto essa esse esta este aquele
the a an of to in on for with without by and or but is are be how what which when where why do does did it this that
preciso quero queria fazer pode podem ser ter tem sao foi era vai vamos favor
""".split()
)

# Sufixos removidos do mais longo ao mais curto (RSLP simplificado + ingles basico). Radical minimo: 4 letras.
_SUFIXOS = tuple(
    sorted(
        (
            "acoes",
            "ucoes",
            "imentos",
            "amentos",
            "adoras",
            "adores",
            "idades",
            "mente",
            "acao",
            "ucao",
            "imento",
            "amento",
            "adora",
            "ador",
            "idade",
            "ivel",
            "avel",
            "istas",
            "ista",
            "ismo",
            "ando",
            "endo",
            "indo",
            "aram",
            "eram",
            "iram",
            "ados",
            "adas",
            "idos",
            "idas",
            "ando",
            "ar",
            "er",
            "ir",
            "ado",
            "ada",
            "ido",
            "ida",
            "oes",
            "ais",
            "eis",
            "res",
            "ing",
            "ings",
            "tion",
            "tions",
            "ness",
            "ment",
            "ments",
            "ers",
            "ed",
            "es",
            "s",
        ),
        key=len,
        reverse=True,
    )
)


def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


_PLURAIS = (("oes", "ao"), ("aes", "ao"), ("aos", "ao"), ("ais", "al"), ("eis", "el"), ("ois", "ol"), ("ns", "m"))


def radical(token: str) -> str:
    """Radical aproximado (>= 4 letras). Nao e linguisticamente perfeito: serve para casar prefixos de forma barata."""
    t = sem_acento(token.casefold())
    if len(t) <= 4 or not t.isalpha():
        return t
    for plural, singular in _PLURAIS:  # "acoes" -> "acao", "autenticacoes" -> "autenticacao"
        if t.endswith(plural) and len(t) - len(plural) >= 2:
            t = t[: -len(plural)] + singular
            break
    for suf in _SUFIXOS:
        if t.endswith(suf) and len(t) - len(suf) >= 4:
            return t[: len(t) - len(suf)]
    return t


# Grupos de sinonimos tecnicos embutidos (minimos). O arquivo publico knowledge/ontologias/sinonimos.json os estende.
SINONIMOS_PADRAO: tuple[tuple[str, ...], ...] = (
    ("autenticar", "autenticacao", "login", "logar", "entrar", "signin", "authenticate", "authentication"),
    ("erro", "falha", "excecao", "exception", "error", "failure", "bug"),
    ("excluir", "apagar", "remover", "deletar", "delete", "remove"),
    ("criar", "gerar", "adicionar", "create", "add"),
    ("configuracao", "config", "configurar", "settings", "parametro"),
    ("banco", "database", "sqlite", "db", "persistencia"),
    ("teste", "test", "pytest", "validacao"),
    ("segredo", "credencial", "senha", "token", "secret", "password", "credential"),
    ("rede", "network", "http", "requisicao", "request"),
    ("lento", "demora", "performance", "desempenho", "latencia", "slow", "latency"),
    ("implantar", "deploy", "publicar", "release", "entrega"),
    ("registro", "log", "logs", "logging", "auditoria"),
    ("fila", "queue", "mensageria"),
    ("permissao", "autorizacao", "acesso", "acl", "permission", "authorization"),
)


@lru_cache(maxsize=8)
def _carregar_sinonimos(caminho: str | None) -> dict[str, tuple[str, ...]]:
    grupos = [list(g) for g in SINONIMOS_PADRAO]
    if caminho and Path(caminho).is_file():
        try:
            dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
            grupos += [list(g) for g in dados.get("grupos", []) if isinstance(g, list)]
        except (OSError, ValueError):
            pass  # arquivo ausente/invalido nunca derruba a busca
    mapa: dict[str, set[str]] = {}
    for g in grupos:
        norm = {sem_acento(str(x).casefold()) for x in g if re.fullmatch(r"\w+", sem_acento(str(x)))}
        for termo in norm:
            mapa.setdefault(termo, set()).update(norm - {termo})
    return {k: tuple(sorted(v)) for k, v in mapa.items()}


def sinonimos_de(token: str, caminho: str | None = None) -> tuple[str, ...]:
    mapa = _carregar_sinonimos(caminho)
    t = sem_acento(token.casefold())
    achados = set(mapa.get(t, ()))
    r = radical(t)
    if r != t:
        achados |= set(mapa.get(r, ()))
    return tuple(sorted(achados - {t}))


def termos_relevantes(tokens: list[str]) -> list[str]:
    """Remove stopwords, mantendo ao menos um termo (consulta so de stopwords nao pode ficar vazia)."""
    uteis = [t for t in tokens if sem_acento(t.casefold()) not in STOPWORDS]
    return uteis or tokens[:1]


def grupos_de_expansao(
    tokens: list[str], caminho_sinonimos: str | None = None, limite_sinonimos: int = 6
) -> list[list[str]]:
    """Para cada termo: [termo, radical*, sinonimos...]. O prefixo '*' e marcado no proprio item."""
    grupos: list[list[str]] = []
    for tok in termos_relevantes(tokens):
        base = sem_acento(tok.casefold())
        alternativas = [base]
        r = radical(base)
        if len(r) >= 4:  # prefixo do radical: "autenticacao" -> "autentic*"; "cliente" -> "cliente*" (casa ClienteAcp)
            alternativas.append(r + "*")
        alternativas += list(sinonimos_de(base, caminho_sinonimos))[:limite_sinonimos]
        grupos.append(alternativas)
    return grupos


def montar_match(grupos: list[list[str]], modo: str = "and") -> str:
    """MATCH do FTS5 seguro: cada alternativa entre aspas (neutraliza operadores); prefixo so onde marcado."""
    partes = []
    for alts in grupos:
        itens = []
        for a in alts:
            prefixo = a.endswith("*")
            nucleo = a.rstrip("*").replace('"', "")
            if nucleo:
                itens.append(f'"{nucleo}"' + ("*" if prefixo else ""))
        if itens:
            partes.append("(" + " OR ".join(itens) + ")" if len(itens) > 1 else itens[0])
    return (" OR " if modo == "or" else " AND ").join(partes)
