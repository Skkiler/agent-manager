"""Perfil de agente "forja" para o Kiro (CLI V3): regras DENY nativas para segredos + presets por nivel de autonomia.

Por que existe (achado no Kiro real, kiro-cli 3.1.0): a politica padrao do Kiro LE QUALQUER ARQUIVO da pasta de trabalho em
silencio, inclusive `.env`; o pedido de permissao nunca chega ao mediador da Forja. Com uma pasta de projeto real como diretorio
de trabalho, isso vaza segredos. O perfil abaixo e aplicado como MODO da sessao (session/set_config_option "mode"); `deny` e a
regra mais forte do Kiro (vence qualquer preset ou aprovacao). A Forja escreve o arquivo; o agente nao pode altera-lo (o Kiro pede
confirmacao para escrita em ~/.kiro/agents).

Niveis -> presets do Kiro (pedidos em session/new `_meta.kiro.policyPreset`):
  restrito: read-workspace (le a pasta de trabalho sem perguntar; segredos negados; editar e rodar comando perguntam)
  liberado/total: edit-workspace (le e edita a pasta de trabalho sem perguntar). Comandos passam SEMPRE pelo mediador da Forja
  (nao usamos dev-shell: ele libera `cat`/`grep` em silencio, o que poderia imprimir segredos sem a Forja ver o comando).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("forja.kiro.perfil")
NOME = "forja"
SEGREDOS = ["**/.env", "**/.env.*", "**/*.pem", "**/*.key", "**/*.p12", "**/*.pfx", "**/*.jks", "**/*.kdbx", "**/id_rsa*", "**/id_ed25519*",
            "**/credentials", "**/credentials.json", "**/secrets/**", "**/secrets.json", "**/secrets.yaml", "**/api_token.txt", "**/.netrc",
            "**/.npmrc", "**/.pypirc"]
MODELOS_PERMITIDOS = ["**/.env.example", "**/.env.sample", "**/.env.template"]  # modelos sem valor: podem ser lidos
SHELL_IMPRIME = ["cat *.env*", "type *.env*", "Get-Content *.env*", "gc *.env*", "more *.env*", "less *.env*", "head *.env*", "tail *.env*",
                 "printenv*", "env", "set", "docker compose config*", "docker-compose config*", "docker inspect*", "docker container inspect*"]
PRESETS = {"restrito": ["read-workspace"], "liberado": ["edit-workspace"], "total": ["edit-workspace"]}


def montar(protegidas: list[Path] | None = None) -> dict:
    extras = [f"{Path(p).resolve().as_posix()}/**" for p in (protegidas or [])]  # perfil do usuario da Forja (banco, credenciais)
    regras = [
        {"capability": "fs_read", "match": SEGREDOS + extras, "exclude": MODELOS_PERMITIDOS, "effect": "deny"},
        {"capability": "fs_write", "match": SEGREDOS + extras, "effect": "deny"},
        {"capability": "shell", "match": SHELL_IMPRIME, "effect": "deny"},
    ]
    return {"name": NOME, "description": "Perfil gerado pela Forja: bloqueia leitura de segredos (gerado automaticamente; nao edite).",
            "tools": ["read", "write", "shell", "web", "@forja"], "permissions": {"rules": regras}}


def garantir(pasta_agentes: Path | None = None, protegidas: list[Path] | None = None) -> Path:
    """Grava (ou mantem) ~/.kiro/agents/forja.json. Idempotente: so reescreve se o conteudo mudou."""
    pasta = pasta_agentes or (Path.home() / ".kiro" / "agents")
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / f"{NOME}.json"
    conteudo = json.dumps(montar(protegidas), ensure_ascii=False, indent=1)
    if not arq.is_file() or arq.read_text(encoding="utf-8") != conteudo:
        arq.write_text(conteudo, encoding="utf-8")
        log.info("perfil de agente do Kiro atualizado", extra={"evento": "kiro.perfil_gravado"})
    return arq
