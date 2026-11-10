"""Indexador de arquivos: varredura segura, simbolos (AST Python), trechos textuais e hashes. Sem banco, sem rede.

Principios (secao 10.4): indexar por SHA-256 (nao por timestamp); fallback textual; um arquivo invalido NUNCA derruba o
projeto; nada de symlinks, segredos, binarios ou arquivos enormes.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from forja.seguranca.acoes import caminho_sensivel
from forja.seguranca.pastas import proibido

MAX_BYTES = 1_000_000
JANELA_LINHAS = 60
SOBREPOSICAO = 10
IGNORAR_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "data",
        "logs",
        "models",
        "cache",
        "backups",
        "dist",
        "build",
        "htmlcov",
        "referencias-visuais-privadas",
        "segundo-cerebro",
        "memoria-local",
    }
)
LINGUAGENS = {
    ".py": "python",
    ".md": "markdown",
    ".txt": "texto",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".js": "javascript",
    ".ts": "typescript",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
    ".ps1": "powershell",
    ".sh": "shell",
    ".rst": "rst",
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


def listar_arquivos(raiz: Path, extensoes: frozenset[str] | None = None) -> Iterator[Path]:
    """Percorre `raiz` sem seguir links e sem sair dela. Ignora diretorios de cache/dados e arquivos sensiveis.
    `extensoes` (ex.: {'.py', '.md'}) restringe o escopo; vazio/None = todas as linguagens conhecidas."""
    permitidas = extensoes or frozenset(LINGUAGENS)
    base = raiz.resolve()
    for atual, dirs, arquivos in os.walk(base, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORAR_DIRS and not d.endswith(".egg-info")
                      and not proibido(Path(atual) / d))
        for nome in sorted(arquivos):
            p = Path(atual) / nome
            if p.is_symlink() or p.suffix.lower() not in permitidas or caminho_sensivel(nome):
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


_RE_JS = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\*?\s+(?P<fn>[A-Za-z_$][\w$]*)|"
    r"class\s+(?P<cl>[A-Za-z_$][\w$]*)|interface\s+(?P<it>[A-Za-z_$][\w$]*)|type\s+(?P<tp>[A-Za-z_$][\w$]*)\s*=|"
    r"(?:const|let|var)\s+(?P<ar>[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>)"
)
_RE_PS = re.compile(r"^\s*function\s+(?P<fn>[A-Za-z_][\w-]*)", re.IGNORECASE)
_RE_SQL = re.compile(
    r"^\s*create\s+(?:or\s+replace\s+)?(?P<k>table|view|function|procedure|index)\s+(?:if\s+not\s+exists\s+)?"
    r"(?P<n>[\w.\[\]\"`]+)",
    re.IGNORECASE,
)
_RE_MD = re.compile(r"^(?P<h>#{1,6})\s+(?P<t>.+?)\s*#*\s*$")


def extrair_simbolos_generico(linguagem: str, texto: str) -> list[Simbolo]:
    """Extracao leve por regex (sem Tree-sitter): secoes de Markdown, funcoes/classes JS/TS, funcoes PowerShell, DDL SQL.
    Falhar aqui nunca derruba a ingestao: o chamador captura qualquer excecao."""
    saida: list[Simbolo] = []
    em_bloco = False
    for n, linha in enumerate(texto.splitlines(), start=1):
        if linguagem == "markdown":
            if linha.lstrip().startswith("```"):
                em_bloco = not em_bloco
                continue
            m = None if em_bloco else _RE_MD.match(linha)
            if m:
                saida.append(Simbolo(m.group("t").strip()[:200], "secao", n, m.group("h")))
        elif linguagem in ("javascript", "typescript"):
            m = _RE_JS.match(linha)
            if m:
                tipo = "classe" if (m.group("cl") or m.group("it") or m.group("tp")) else "funcao"
                nome = next(g for g in m.group("fn", "cl", "it", "tp", "ar") if g)
                saida.append(Simbolo(nome, tipo, n))
        elif linguagem == "powershell":
            m = _RE_PS.match(linha)
            if m:
                saida.append(Simbolo(m.group("fn"), "funcao", n))
        elif linguagem == "sql":
            m = _RE_SQL.match(linha)
            if m:
                saida.append(
                    Simbolo(
                        m.group("n").strip('[]"`'),
                        "tabela" if m.group("k").lower() == "table" else m.group("k").lower(),
                        n,
                    )
                )
    return saida


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


def eh_minificado(nome: str, texto: str) -> bool:
    """`*.min.js|css`, ou texto com linhas gigantes (media > 400 car./linha em arquivo >= 2 KB) = minificado/empacotado."""
    if nome.casefold().endswith((".min.js", ".min.css", ".bundle.js", ".map")):
        return True
    if len(texto) < 2048:
        return False
    return len(texto) / (texto.count("\n") + 1) > 400


def analisar(raiz: Path, caminho: Path) -> ArquivoAnalisado | None:
    """None para binarios/ilegiveis. Erro de sintaxe NAO descarta o arquivo: cai no fallback textual."""
    try:
        dados = caminho.read_bytes()
    except OSError:
        return None
    if b"\x00" in dados[:8192]:
        return None
    texto = dados.decode("utf-8", errors="replace")
    if eh_minificado(caminho.name, texto):
        return None  # biblioteca empacotada/minificada: ruido puro para busca de codigo
    rel = caminho.resolve().relative_to(raiz.resolve()).as_posix()
    ling = LINGUAGENS.get(caminho.suffix.lower(), "texto")
    arq = ArquivoAnalisado(rel, sha256_bytes(dados), ling, len(dados), texto)
    try:
        if ling == "python":
            arq.simbolos = extrair_simbolos(texto)
        else:
            arq.simbolos = extrair_simbolos_generico(ling, texto)
    except (SyntaxError, ValueError, RecursionError, StopIteration) as e:
        arq.erro_parse = f"{type(e).__name__}: {str(e)[:120]}"
    arq.trechos = dividir_trechos(texto)
    return arq
