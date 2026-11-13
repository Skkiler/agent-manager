"""Verificacao deterministica da Forja: descobre o comando de testes do projeto e o executa com protecoes.

Base da "rodada unica de correcao" (padrao avaliador-otimizador): quem confere o trabalho do agente e um comando real,
nao a palavra do modelo. Rodar testes executa codigo do projeto, entao:
- so com aprovacao do operador (ou nivel 'total', que ja aprova comandos dentro da pasta);
- sem shell (lista de argumentos), dentro da pasta de trabalho, com tempo maximo;
- ambiente LIMPO: variaveis com cara de segredo e as da propria Forja (APP_*, FORJA_*) nao chegam ao processo;
- a saida volta redigida e cortada (so a cauda, onde fica o resumo do runner).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from forja.observabilidade.sanitizar import redigir_segredos

MAX_SAIDA = 12_000
_SEGREDO_NOME = re.compile(r"(?i)(token|secret|senha|password|passwd|api[_-]?key|credential|private|auth|cookie|session)")
_MANTER = frozenset({"PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE",
                     "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "LANG", "LC_ALL", "TERM",
                     "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS", "USERNAME", "HOMEDRIVE", "HOMEPATH", "VIRTUAL_ENV",
                     "PYTHONIOENCODING", "NODE_ENV", "CI"})


@dataclass(frozen=True)
class ComandoTeste:
    tipo: str  # pytest | npm | cargo | go
    args: tuple[str, ...]

    @property
    def texto(self) -> str:
        return " ".join(Path(self.args[0]).name if i == 0 else a for i, a in enumerate(self.args))

    def com_alvos(self, alvos: list[str]) -> ComandoTeste:
        """Versao direcionada (so pytest aceita arquivos de teste como argumento de forma confiavel)."""
        return ComandoTeste(self.tipo, (*self.args, *alvos)) if self.tipo == "pytest" and alvos else self


@dataclass
class ResultadoTeste:
    comando: str
    ok: bool
    codigo: int | None
    segundos: float
    saida: str
    tempo_esgotado: bool = False
    resumo: str = ""
    falhas: list[str] = field(default_factory=list)
    isolamento: dict = field(default_factory=dict)  # {modo, grupo, teto_memoria}: o que o isolamento conseguiu aplicar


def _python_do_projeto(cwd: Path) -> str:
    for rel in (".venv/Scripts/python.exe", "venv/Scripts/python.exe", ".venv/bin/python", "venv/bin/python"):
        p = cwd / rel
        if p.is_file() and not p.is_symlink():
            return str(p)
    return shutil.which("python") or shutil.which("python3") or sys.executable


def detectar(cwd: Path) -> ComandoTeste | None:
    """Comando de testes pelo que o projeto declara (nunca inventa um comando arbitrario)."""
    if (cwd / "pytest.ini").is_file() or (cwd / "conftest.py").is_file() or (cwd / "tests").is_dir() and any(
            (cwd / "tests").glob("test_*.py")) or "[tool.pytest" in _ler(cwd / "pyproject.toml"):
        return ComandoTeste("pytest", (_python_do_projeto(cwd), "-m", "pytest", "-q", "-rfE", "--no-header", "-p", "no:cacheprovider"))
    pacote = cwd / "package.json"
    if pacote.is_file():
        try:
            teste = (json.loads(_ler(pacote) or "{}").get("scripts") or {}).get("test", "")
        except ValueError:
            teste = ""
        npm = shutil.which("npm")
        if teste and "no test specified" not in teste and npm:
            return ComandoTeste("npm", (npm, "test", "--silent"))
    if (cwd / "Cargo.toml").is_file() and shutil.which("cargo"):
        return ComandoTeste("cargo", (shutil.which("cargo") or "cargo", "test", "--quiet"))
    if (cwd / "go.mod").is_file() and shutil.which("go"):
        return ComandoTeste("go", (shutil.which("go") or "go", "test", "./..."))
    return None


def _ler(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace") if p.is_file() and p.stat().st_size < 1_000_000 else ""
    except OSError:
        return ""


def ambiente_limpo(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    return {k: v for k, v in env.items()
            if (k.upper() in _MANTER or not (k.upper().startswith(("APP_", "FORJA_")) or _SEGREDO_NOME.search(k)))}


def _resumir(cmd: ComandoTeste, saida: str) -> tuple[str, list[str]]:
    if cmd.tipo == "pytest":
        from forja.ferramentas.testes import resumir_pytest

        r = resumir_pytest(saida, 10)
        falhas = [f"{f.get('id', '')}: {f.get('msg', '')}".strip(": ") for f in (r.dados.get("falhas") or []) if isinstance(f, dict)]
        return r.resumo, falhas[:10]
    cauda = [x for x in saida.splitlines() if x.strip()][-15:]
    return "\n".join(cauda), []


def rodar(cmd: ComandoTeste, cwd: Path, timeout: float = 300.0, isolamento: str = "basico") -> ResultadoTeste:
    """`isolamento`: basico (grupo de processos, teto de memoria, TMP proprio) | estrito (+ HOME proprio e sem rede).
    Ver forja/ferramentas/sandbox.py."""
    from forja.ferramentas import sandbox

    t0 = time.monotonic()
    env = ambiente_limpo()
    cache_pyc = None
    info: dict = {}
    if cmd.tipo == "pytest":
        # Bytecode NOVO a cada rodada: o .pyc e validado por mtime (em segundos) + tamanho; uma correcao do agente com o MESMO
        # tamanho no mesmo segundo carregaria o codigo antigo e os testes "continuariam falhando". Nunca usa o __pycache__ do projeto.
        cache_pyc = tempfile.mkdtemp(prefix="forja-pyc-")
        env["PYTHONPYCACHEPREFIX"] = cache_pyc
    try:
        s = sandbox.executar(list(cmd.args), cwd, env, timeout, isolamento)
        saida, codigo, esgotado, info = s.texto, s.codigo, s.esgotado, s.isolamento
    except OSError as e:
        saida, codigo, esgotado = f"[nao foi possivel executar: {type(e).__name__}]", None, False
    finally:
        if cache_pyc:
            shutil.rmtree(cache_pyc, ignore_errors=True)
    saida = redigir_segredos(saida[-MAX_SAIDA:])
    resumo, falhas = _resumir(cmd, saida)
    # pytest: 5 = nenhum teste coletado (nao e sucesso nem falha do codigo)
    ok = codigo == 0
    return ResultadoTeste(cmd.texto, ok, codigo, round(time.monotonic() - t0, 2), saida, esgotado, resumo, falhas, info)
