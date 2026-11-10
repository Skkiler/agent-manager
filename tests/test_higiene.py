"""Higiene do repositorio: arquivos de texto em UTF-8 sem BOM (o pip e ferramentas de AST falham com BOM)."""

from __future__ import annotations

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
EXTENSOES = {".py", ".txt", ".md", ".js", ".css", ".html", ".yml", ".yaml", ".toml", ".json", ".webmanifest", ".ini"}
IGNORAR = {".git", ".venv", "venv", "node_modules", "data", "logs", "__pycache__", ".pytest_cache", ".ruff_cache"}


def test_nenhum_arquivo_de_texto_tem_bom():
    com_bom = [p.relative_to(RAIZ).as_posix() for p in RAIZ.rglob("*")
               if p.is_file() and p.suffix in EXTENSOES and not (set(p.relative_to(RAIZ).parts) & IGNORAR)
               and p.read_bytes()[:3] == b"\xef\xbb\xbf"]
    assert not com_bom, com_bom
