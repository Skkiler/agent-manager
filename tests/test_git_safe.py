"""Regra de publicacao: logica e publica; credenciais, dados internos e segundo cerebro NUNCA sobem ao Git.

Estes testes quebram se alguem remover uma protecao do .gitignore/.kiroignore (o repositorio e publico).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PRIVADOS = [
    ".env", ".env.local", "data/forja.sqlite3", "data/api_token.txt", "data/artefatos/ab/abcdef",
    "data/kiro-workspace/x.txt", "logs/app.log", "models/m.gguf", "backups/b.sqlite3", "x.sqlite3", "x.db", "x.har",
    "chave.pem", "id_rsa", "credentials.json", "secrets/a.yaml", "private/x.md",
    "knowledge/privado/nota.md", "knowledge/pessoal/nota.md", "knowledge/empresa/acme/doc.md",
    "knowledge/terceiros/doc.md", "memoria-local/x", "segundo-cerebro/nota.md", "grafo.brain", "x.memoria.json",
    "referencias-visuais-privadas/sprite.png",
]
PUBLICOS = [
    ".env.example", "forja/memoria/modelo.py", "knowledge/ontologias/base.md", "knowledge/procedimentos/demo.md",
    "knowledge/modelos_publicos/exemplo.json", "docs/adr/0007-memoria.md", "tests/test_git_safe.py",
]


def _ignorado(caminho: str, arquivo_ignore: str = ".gitignore") -> bool:
    r = subprocess.run(  # noqa: S603 - args fixos
        ["git", "check-ignore", "--no-index", "-q", caminho], cwd=RAIZ, capture_output=True, check=False)
    return r.returncode == 0


pytestmark = pytest.mark.skipif(shutil.which("git") is None or not (RAIZ / ".gitignore").exists(),
                                reason="git ou .gitignore indisponivel")


@pytest.mark.parametrize("caminho", PRIVADOS)
def test_caminhos_privados_sao_ignorados_pelo_git(caminho):
    assert _ignorado(caminho), f"{caminho} NAO esta no .gitignore: risco de publicar dado privado"


@pytest.mark.parametrize("caminho", PUBLICOS)
def test_codigo_e_exemplos_publicos_nao_sao_ignorados(caminho):
    assert not _ignorado(caminho), f"{caminho} nao pode ser ignorado (e conteudo publico do projeto)"


@pytest.fixture(scope="module")
def repo_kiroignore(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Repo git descartavel onde o .kiroignore vira .gitignore: a semantica de padroes e a REAL do git, nao a nossa."""
    d = tmp_path_factory.mktemp("kiroignore")
    subprocess.run(["git", "init", "-q"], cwd=d, check=True, capture_output=True)  # noqa: S607
    shutil.copyfile(RAIZ / ".kiroignore", d / ".gitignore")
    return d


@pytest.mark.parametrize("caminho", [p for p in PRIVADOS if p != "referencias-visuais-privadas/sprite.png"])
def test_agente_kiro_tambem_nao_le_o_que_e_privado(caminho, repo_kiroignore):
    """.kiroignore e a defesa extra do agente (nao substitui o .gitignore): cada privado deve estar coberto."""
    r = subprocess.run(["git", "check-ignore", "--no-index", "-q", caminho], cwd=repo_kiroignore,  # noqa: S607
                       capture_output=True, check=False)
    assert r.returncode == 0, f"{caminho} nao coberto por .kiroignore (o agente poderia le-lo)"


def test_nenhum_arquivo_privado_esta_rastreado():
    r = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=False)  # noqa: S607
    if r.returncode != 0:
        pytest.skip("nao e um repositorio git")
    rastreados = r.stdout.splitlines()
    proibidos = [f for f in rastreados if f.startswith(("data/", "logs/", "models/", "backups/", "segundo-cerebro/",
                                                         "memoria-local/", "knowledge/privado/", "knowledge/pessoal/",
                                                         "knowledge/empresa/", "knowledge/terceiros/"))
                 or f == ".env" or f.endswith((".sqlite3", ".db", ".pem", ".key", ".har", ".brain"))]
    assert proibidos == [], f"arquivos privados rastreados pelo Git: {proibidos}"
