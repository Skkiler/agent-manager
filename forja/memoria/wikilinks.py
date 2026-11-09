"""Extracao de [[wikilinks]] e #tags no estilo Obsidian. Puro: sem I/O."""

from __future__ import annotations

import re

WIKILINK = re.compile(r"\[\[([^\[\]|#\n]{1,200})(?:[#|][^\[\]\n]*)?\]\]")
TAG = re.compile(r"(?<![\w/])#([A-Za-z\u00C0-\u00FF][\w/-]{0,49})")
_CODIGO = re.compile(r"```.*?```|`[^`\n]*`", re.S)


def extrair_wikilinks(texto: str) -> list[str]:
    """Titulos citados como [[Titulo]], [[Titulo|alias]] ou [[Titulo#secao]], sem repeticao e na ordem em que aparecem."""
    vistos: dict[str, None] = {}
    for m in WIKILINK.finditer(texto or ""):
        vistos.setdefault(m.group(1).strip(), None)
    return [t for t in vistos if t]


def extrair_tags(texto: str) -> list[str]:
    """#tags do corpo (ignora blocos de codigo e cabecalhos Markdown como '# Titulo')."""
    limpo = _CODIGO.sub(" ", texto or "")
    return list(dict.fromkeys(m.group(1) for m in TAG.finditer(limpo)))
