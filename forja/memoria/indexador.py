"""Indexador de arquivos: varredura segura, simbolos (AST Python), trechos textuais e hashes. Sem banco, sem rede.

Principios (secao 10.4): indexar por SHA-256 (nao por timestamp); fallback textual; um arquivo invalido NUNCA derruba o
projeto; nada de symlinks, segredos, binarios ou arquivos enormes.
"""

from __future__ import annotations

import ast
import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from forja.seguranca.acoes import caminho_sensivel

MAX_BYTES = 1_000_000
JANELA_LINHAS = 60
SOBREPOSICAO = 10
IGNORAR_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    "data", "logs", "models", "cache", "backups", "dist", "build", "htmlcov", "referencias-visuais-privadas",
    "segundo-cerebro", "memoria-local",
})
LINGUAGENS = {
    ".py": "python", ".md": "markdown", ".txt": "texto", ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".ini": "ini", ".js": "javascript", ".ts": "typescript", ".html": "html", ".css": "css",
    ".sql": "sql", ".ps1": "powershell", ".sh": "shell", ".rst": "rst",
}


@dataclass(frozen=True)
class Simbolo:
    nome: str
    tipo: str  # classe | funcao | metodo | import
    linha: int
    assinatura: str = ""


@dataclass
class ArquivoAnalisado:
    caminho: str  # relativo a raiz, separador '/'
    sha256: str
    linguagem: str
    tamanho: int
    texto: str
    simbolos: list[Simbolo] = field(default_factory=list)
    trechos: list[tuple[int, int, str]] = field(default_factory=list)  # (linha_ini, linha_fim, texto)
    erro_parse: str | None = None


def sha256_bytes(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def listar_arquivos(raiz: Path) -> Iterator[Path]:
    """Percorre `raiz` sem seguir links e sem sair dela. Ignora diretorios de cache/dados e arquivos sensiveis."""
    base = raiz.resolve()
    for atual, dirs, arquivos in os.walk(base, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORAR_DIRS and not d.endswith(".egg-info"))
        for nome in sorted(arquivos):
            p = Path(atual) / nome
            if p.is_symlink() or p.suffix.lower() not in LINGUAGENS or caminho_sensivel(nome):
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue
                p.resolve().relative_to(base)
            except (OSError, ValueError):
                continue
            yield p


def extrair_simbolos(texto: str) -> list[Simbolo]:
    arvore = ast.parse(texto)
    simbolos: list[Simbolo] = []

    def visitar(no: ast.AST, classe: str | None) -> None:
        for filho in ast.iter_child_nodes(no):
            if isinstance(filho, ast.ClassDef):
                simbolos.append(Simbolo(filho.name, "classe", filho.lineno))
                visitar(filho, filho.name)
            elif isinstance(filho, ast.FunctionDef | ast.AsyncFunctionDef):
                nome = f"{classe}.{filho.name}" if classe else filho.name
                args = ", ".join(a.arg for a in filho.args.args)
                simbolos.append(Simbolo(nome, "metodo" if classe else "funcao", filho.lineno, f"({args})"))
                visitar(filho, classe)
            elif isinstance(filho, ast.Import):
                simbolos.extend(Simbolo(a.name, "import", filho.lineno) for a in filho.names)
            elif isinstance(filho, ast.ImportFrom):
                simbolos.append(Simbolo(filho.module or ".", "import", filho.lineno))

    visitar(arvore, None)
    return simbolos


def dividir_trechos(texto: str) -> list[tuple[int, int, str]]:
    linhas = texto.splitlines()
    if not linhas:
        return []
    trechos, ini = [], 0
    while ini < len(linhas):
        fim = min(ini + JANELA_LINHAS, len(linhas))
        trechos.append((ini + 1, fim, "\n".join(linhas[ini:fim])))
        if fim == len(linhas):
            break
        ini = fim - SOBREPOSICAO
    return trechos


def analisar(raiz: Path, caminho: Path) -> ArquivoAnalisado | None:
    """None para binarios/ilegiveis. Erro de sintaxe NAO descarta o arquivo: cai no fallback textual."""
    try:
        dados = caminho.read_bytes()
    except OSError:
        return None
    if b"\x00" in dados[:8192]:
        return None
    texto = dados.decode("utf-8", errors="replace")
    rel = caminho.resolve().relative_to(raiz.resolve()).as_posix()
    ling = LINGUAGENS.get(caminho.suffix.lower(), "texto")
    arq = ArquivoAnalisado(rel, sha256_bytes(dados), ling, len(dados), texto)
    if ling == "python":
        try:
            arq.simbolos = extrair_simbolos(texto)
        except (SyntaxError, ValueError, RecursionError) as e:
            arq.erro_parse = f"{type(e).__name__}: {str(e)[:120]}"
    arq.trechos = dividir_trechos(texto)
    return arq
