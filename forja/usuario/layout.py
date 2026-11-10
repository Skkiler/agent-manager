"""Onde vivem os DADOS DO USUARIO, separados do codigo.

Regra do projeto: o repositorio (Git) tem codigo, logica, configuracao padrao e conhecimento publico pre-criado. Tudo o que e
do usuario e o orquestrador aprende/guarda (credenciais, integracoes, memoria e segundo cerebro, notas, ferramentas extras,
preferencias, artefatos e logs) fica numa pasta POR PERFIL, FORA do repositorio:

    <base>/perfis/<perfil>/
        credenciais/   .env do usuario (FORJA_INT_*), api_token.txt     <- nunca sai da maquina
        dados/         banco SQLite (tarefas, memoria, segundo cerebro, preferencias, integracoes configuradas)
        notas/         notas e cofres do usuario            ferramentas/   ferramentas adicionais do usuario
        config/        reservado a arquivos de configuracao   artefatos/ logs/ workspace/ backups/

`<base>` = APP_USER_HOME, ou o diretorio de dados do sistema (Windows: %LOCALAPPDATA%/Forja). `<perfil>` = APP_PROFILE ou o
usuario do sistema. Instalacoes antigas (pasta ./data com banco) continuam funcionando em modo LEGADO ate a migracao
(scripts/migrar_dados_usuario.py), com aviso.
"""

from __future__ import annotations

import getpass
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

SUBPASTAS = ("credenciais", "dados", "notas", "ferramentas", "config", "artefatos", "logs", "workspace", "backups")
MARCADOR_MIGRADO = "MIGRADO.txt"
_PERFIL_OK = re.compile(r"[^a-z0-9_-]+")


class DadosDentroDoRepositorio(RuntimeError):
    """Os dados do usuario estariam numa pasta versionada pelo Git."""


def base_da_plataforma() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Forja"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Forja"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "forja"


def nome_do_perfil(valor: str | None = None) -> str:
    bruto = (valor or "").strip() or _usuario_do_sistema()
    limpo = _PERFIL_OK.sub("-", bruto.lower()).strip("-")[:40]
    return limpo or "default"


def _usuario_do_sistema() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - ambientes sem usuario (containers)
        return "default"


def raiz_do_repositorio(inicio: Path | None = None) -> Path | None:
    """Pasta que contem `.git` acima de `inicio` (padrao: este pacote) ou None se nao for um repositorio."""
    atual = (inicio or Path(__file__)).resolve()
    for p in [atual, *atual.parents]:
        if (p / ".git").exists():
            return p
    return None


def ignorado_pelo_git(caminho: Path, repo: Path) -> bool:
    try:
        r = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", "--", str(caminho)],  # noqa: S603, S607
                           capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


@dataclass(frozen=True)
class PerfilUsuario:
    raiz: Path
    perfil: str
    legado: bool = False

    def pasta(self, nome: str) -> Path:
        if nome not in SUBPASTAS:
            raise KeyError(nome)
        if self.legado:  # layout antigo: tudo em ./data (logs em ./logs; workspace do Kiro em ./data/kiro-workspace)
            if nome == "logs":
                return Path("./logs")
            return self.raiz if nome in ("dados", "credenciais") else self.raiz / ("kiro-workspace" if nome == "workspace" else nome)
        return self.raiz / nome

    @property
    def dados(self) -> Path:
        return self.pasta("dados")

    @property
    def credenciais(self) -> Path:
        return self.pasta("credenciais")

    @property
    def logs(self) -> Path:
        return self.pasta("logs")

    @property
    def arquivo_env(self) -> Path:
        return self.credenciais / ".env"

    def criar(self) -> None:
        """Cria as pastas (somente dono, quando o SO suporta) e um LEIA-ME em cada uma na primeira vez."""
        for nome in SUBPASTAS:
            p = self.pasta(nome)
            p.mkdir(parents=True, exist_ok=True)
            if os.name == "posix":
                p.chmod(0o700)
        if not self.legado:
            leia = self.raiz / "LEIA-ME.txt"
            if not leia.exists():
                leia.write_text(
                    "Dados LOCAIS do usuario da Forja. Nao copie esta pasta para o Git nem compartilhe: contem credenciais,\n"
                    "memoria/segundo cerebro, notas e preferencias. Faca backup por conta propria (scripts/backup).\n", encoding="utf-8")

    def resumo(self) -> dict:
        return {"perfil": self.perfil, "raiz": str(self.raiz), "legado": self.legado,
                "pastas": {n: str(self.pasta(n)) for n in SUBPASTAS}}


def resolver_perfil(ambiente: dict[str, str] | None = None, cwd: Path | None = None, permitir_legado: bool = True) -> PerfilUsuario:
    """Decide o perfil. Ordem: APP_USER_HOME explicito > legado (./data com banco e sem MIGRADO.txt) > pasta padrao do SO."""
    cwd = cwd or Path.cwd()
    env = dict(ambiente) if ambiente is not None else {**_chaves_do_env(cwd / ".env"), **os.environ}
    perfil = nome_do_perfil(env.get("APP_PROFILE"))
    home = (env.get("APP_USER_HOME") or "").strip()
    if home:
        return PerfilUsuario(Path(home).expanduser() / "perfis" / perfil, perfil)
    legado = cwd / "data"
    if permitir_legado and (legado / "forja.sqlite3").exists() and not (legado / MARCADOR_MIGRADO).exists():
        return PerfilUsuario(Path("./data"), perfil, legado=True)
    return PerfilUsuario(base_da_plataforma() / "perfis" / perfil, perfil)


def _chaves_do_env(arquivo: Path) -> dict[str, str]:
    try:
        v = dotenv_values(arquivo)
    except OSError:
        return {}
    return {k: v[k] for k in ("APP_USER_HOME", "APP_PROFILE") if v.get(k)}


def validar_fora_do_git(perfil: PerfilUsuario, repo: Path | None = None) -> None:
    """Recusa dados do usuario dentro de uma pasta versionada, a menos que o Git a ignore (ex.: ./data legado)."""
    repo = repo if repo is not None else raiz_do_repositorio()
    if repo is None:
        return
    alvo = perfil.raiz.resolve()
    try:
        alvo.relative_to(repo.resolve())
    except ValueError:
        return  # fora do repositorio: o caso desejado
    # testa um arquivo DENTRO da pasta: padroes como "/data/" so casam diretorios que ja existem
    if not ignorado_pelo_git(alvo / "forja.sqlite3", repo):
        raise DadosDentroDoRepositorio(
            f"Os dados do usuario ({alvo}) estao dentro do repositorio e NAO sao ignorados pelo Git. "
            "Defina APP_USER_HOME para uma pasta fora do repositorio.")
