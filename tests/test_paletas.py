"""As 8 paletas do painel: completas, separadas em 4 escuras + 4 claras e com contraste WCAG AA (4,5:1) nos pares usados."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from forja.preferencias.registro import POR_ID

TEMA = (Path(__file__).resolve().parents[1] / "forja" / "painel" / "estatico" / "tema.css").read_text(encoding="utf-8")
ESCURAS, CLARAS = ("grafite", "meia_noite", "floresta", "brasa"), ("neve", "papel", "nevoa", "lavanda")
CHAVES = ("bg", "lateral", "ativ", "painel", "cartao", "entrada", "hover", "sel", "borda", "texto", "titulo", "mudo", "acento",
          "acento-forte", "sobre-acento", "acento-bg", "ok", "aviso", "erro", "veu")
# (frente, fundos): o que aparece sobre o que na interface
PARES = [("texto", ("bg", "lateral", "cartao", "entrada", "hover", "sel", "acento-bg", "painel")),
         ("titulo", ("bg", "lateral", "cartao", "sel", "acento-bg")),
         ("mudo", ("bg", "lateral", "ativ", "cartao", "painel", "entrada")),
         ("acento", ("bg", "lateral", "cartao", "painel")),
         ("sobre-acento", ("acento-forte",)),
         ("ok", ("bg", "cartao", "lateral")), ("aviso", ("bg", "cartao", "lateral")), ("erro", ("bg", "cartao", "lateral"))]


def _paleta(nome: str) -> dict[str, str]:
    m = re.search(r':root\[data-paleta="' + nome + r'"\]\s*\{([^}]*)\}', TEMA)
    assert m, f"paleta {nome} ausente"
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{3,8})", m.group(1)))


def _lum(hexa: str) -> float:
    h = hexa.lstrip("#")[:6]
    canais = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canais]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("nome", ESCURAS + CLARAS)
def test_paleta_completa_e_legivel(nome):
    p = _paleta(nome)
    assert set(CHAVES) <= set(p), set(CHAVES) - set(p)
    ruins = [(f, fundo, round(contraste(p[f], p[fundo]), 2)) for f, fundos in PARES for fundo in fundos
             if contraste(p[f], p[fundo]) < 4.5]
    assert not ruins, ruins


@pytest.mark.parametrize("nome", ESCURAS + CLARAS)
def test_escuras_sao_escuras_e_claras_sao_claras(nome):
    escura = _lum(_paleta(nome)["bg"]) < 0.1
    assert escura == (nome in ESCURAS)


def test_preferencias_oferecem_as_mesmas_paletas():
    assert tuple(v for v, _ in POR_ID["paleta_escura"].opcoes) == ESCURAS
    assert tuple(v for v, _ in POR_ID["paleta_clara"].opcoes) == CLARAS
    assert POR_ID["paleta_escura"].padrao == "grafite" and POR_ID["paleta_clara"].padrao == "neve"


def test_sem_js_o_claro_do_sistema_e_a_neve():
    m = re.search(r":root:not\(\[data-paleta\]\)\s*\{([^}]*)\}", TEMA)
    assert m and dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{3,8})", m.group(1))) == _paleta("neve")
