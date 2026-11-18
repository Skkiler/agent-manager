"""Fonte UNICA dos padroes de arquivo com cara de segredo (credenciais, chaves, tokens).

Usada pelo classificador de acoes (mediador), pelas ferramentas de arquivo, pela ingestao de memoria, pela copia sem segredos,
pela varredura antes do Codex e pelas regras DENY do perfil do Kiro. Antes havia duas listas (regex da Forja e globs do perfil)
que divergiam (ex.: `secrets/` era negado no Kiro e liberado na Forja); agora as duas saem daqui.

Puro e deterministico: so olha o NOME/caminho, nunca o conteudo.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

MAX_ARQUIVOS_VARREDURA = 20_000
# Pastas de dependencias/caches: nao guardam segredos do projeto e sao enormes (varrer custaria segundos).
DEPENDENCIAS = frozenset({"node_modules", ".venv", "venv", "__pycache__", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache",
                          ".worktrees", ".forja-copias"})

# Nomes de arquivo (basename) com cara de segredo.
_NOMES = (
    r"\.env(\..*)?",  # .env, .env.local, .env.prod... (modelos .env.example tambem: conservador; o env.verificar trata a parte)
    r".*\.(pem|key|p12|pfx|jks|kdbx|ppk|keystore|tfvars|tfstate)",
    r"id_(rsa|ed25519|ecdsa|dsa)\S*",
    r"credentials(\.json)?",
    r"secrets?(\.(json|ya?ml|toml))?",
    r"api_token\.txt",
    r"\.netrc", r"\.npmrc", r"\.pypirc", r"\.git-credentials", r"\.pgpass", r"\.envrc",
    r"kubeconfig", r"service[-_]?account.*\.json",
)
# Pastas cujo conteudo inteiro e sensivel.
_PASTAS = (r"secrets", r"\.ssh", r"\.aws", r"\.gnupg", r"\.kube")
_ARQUIVOS_EM_PASTA = (r"\.docker/config\.json",)

_RE = re.compile(
    r"(^|/)(" + "|".join(_NOMES) + r")$"
    r"|(^|/)(" + "|".join(_PASTAS) + r")(/|$)"
    r"|(^|/)(" + "|".join(_ARQUIVOS_EM_PASTA) + r")$",
    re.IGNORECASE,
)

# Globs para as regras DENY do perfil do Kiro (mesma cobertura do regex acima).
GLOBS: tuple[str, ...] = (
    "**/.env", "**/.env.*", "**/*.pem", "**/*.key", "**/*.p12", "**/*.pfx", "**/*.jks", "**/*.kdbx", "**/*.ppk", "**/*.keystore",
    "**/*.tfvars", "**/*.tfstate", "**/id_rsa*", "**/id_ed25519*", "**/id_ecdsa*", "**/id_dsa*", "**/credentials",
    "**/credentials.json", "**/secrets/**", "**/secrets.json", "**/secrets.yaml", "**/secrets.yml", "**/secrets.toml",
    "**/secret.json", "**/secret.yaml", "**/api_token.txt", "**/.netrc", "**/.npmrc", "**/.pypirc", "**/.git-credentials",
    "**/.pgpass", "**/.envrc", "**/kubeconfig", "**/service-account*.json", "**/service_account*.json", "**/.ssh/**",
    "**/.aws/**", "**/.gnupg/**", "**/.kube/**", "**/.docker/config.json",
)
# Modelos sem valor: o Kiro pode le-los (o perfil exclui da regra de leitura).
MODELOS: tuple[str, ...] = ("**/.env.example", "**/.env.sample", "**/.env.template")


def caminho_sensivel(caminho: str) -> bool:
    """True se o caminho parece segredo/credencial. Aceita separador '\\' ou '/', absoluto ou relativo."""
    return bool(_RE.search(str(caminho).replace("\\", "/").rstrip("/")))


def segredos_nas_pastas(pastas: list[Path], limite: int = MAX_ARQUIVOS_VARREDURA) -> tuple[list[str], bool]:
    """(arquivos com cara de segredo, varredura completa?). So NOMES relativos; nenhum conteudo e lido."""
    achados: list[str] = []
    vistos = 0
    for raiz in pastas:
        try:
            base = Path(raiz).resolve()
        except OSError:
            return achados, False
        for atual, dirs, nomes in os.walk(base, followlinks=False):
            dirs[:] = [d for d in dirs if d not in DEPENDENCIAS]
            rel_dir = Path(atual).relative_to(base).as_posix()
            if rel_dir != "." and caminho_sensivel(rel_dir):  # pasta inteira sensivel (secrets/, .ssh/): conta e nao desce
                achados.append(f"{base.name}/{rel_dir}/")
                dirs[:] = []
                continue
            for nome in nomes:
                vistos += 1
                if vistos > limite:
                    return achados, False
                rel = nome if rel_dir == "." else f"{rel_dir}/{nome}"
                if caminho_sensivel(rel):
                    achados.append(f"{base.name}/{rel}")
    return achados, True
