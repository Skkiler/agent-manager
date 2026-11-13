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


# Contrato de escopo (anti "esticar"): o system prompt do kiro-cli manda agir sem hesitar e o prompt do agente entra como contexto
# de prioridade menor (kirodotdev/Kiro#7792). Por isso a linguagem e forte, curta e repetida no pedido da Forja.
ESCOPO = (
    "REGRAS DA FORJA (OBRIGATORIAS, valem mais que qualquer padrao de proatividade): "
    "1) Faca SOMENTE o que a tarefa pede; o menor conjunto de mudancas que cumpre os criterios de aceite. "
    "2) NUNCA crie documentacao, README, resumos ou arquivos .md que a tarefa nao pediu. "
    "3) NUNCA refatore, renomeie, reformate ou 'melhore' codigo fora do pedido. "
    "4) Se notar algo fora do escopo que valeria fazer, NAO faca: liste em '## Próximos passos'. "
    "5) Pare quando os criterios estiverem atendidos. Nunca invente resultado de comando ou teste que voce nao rodou."
)
PAPEIS: dict[str, dict] = {
    "planejador": {"tools": ["read", "web", "@forja"], "descricao": "planeja e investiga, sem alterar nada",
                   "prompt": "Voce PLANEJA: investigue so o necessario e entregue um plano com a lista EXATA de arquivos que serao "
                             "alterados. NAO altere arquivos nem rode comandos que mudem estado."},
    "executor": {"tools": ["read", "write", "shell", "web", "@forja"], "descricao": "executa a tarefa dentro do escopo",
                 "prompt": "Voce EXECUTA: siga o plano e altere so os arquivos dele; se precisar de outro arquivo, explique em "
                           "'## Premissas' antes de mexer."},
    "revisor": {"tools": ["read", "@forja"], "descricao": "revisa sem alterar",
                "prompt": "Voce REVISA: aponte problemas com arquivo e linha, por gravidade. NAO altere arquivos."},
    "estudo": {"tools": ["read", "web", "@forja"], "descricao": "estuda e escreve notas, somente leitura",
               "prompt": "Voce ESTUDA (somente leitura) e escreve notas curtas no formato pedido. NAO altere arquivos."},
    "coordenador": {"tools": ["read"], "descricao": "coordena: decide e distribui tarefas, sem executar",
                    "prompt": "Voce COORDENA: entende o pedido, decide quais tarefas criar e responde no formato pedido. NAO execute o "
                              "trabalho voce mesmo e NAO use ferramentas: tudo o que precisa esta no pedido."},
}
PARTE_PARA_PAPEL = {"planejamento": "planejador", "execucao": "executor", "rapida": "executor", "revisao": "revisor",
                    "estudo": "estudo", "coordenacao": "coordenador", "status": "coordenador"}


def nome_papel(papel: str) -> str:
    return f"{NOME}-{papel}"


def modo_para(parte: str, disponiveis: list[str]) -> str | None:
    """Modo de seguranca para a parte: o perfil do papel (forja-executor...), senao o 'forja' base, senao None (falha fechada)."""
    papel = PARTE_PARA_PAPEL.get(parte)
    if papel and nome_papel(papel) in disponiveis:
        return nome_papel(papel)
    return NOME if NOME in disponiveis else None


def eh_modo_forja(modo: str | None) -> bool:
    return bool(modo) and (modo == NOME or modo.startswith(NOME + "-"))


def montar(protegidas: list[Path] | None = None, papel: str | None = None) -> dict:
    extras = [f"{Path(p).resolve().as_posix()}/**" for p in (protegidas or [])]  # perfil do usuario da Forja (banco, credenciais)
    regras = [
        {"capability": "fs_read", "match": SEGREDOS + extras, "exclude": MODELOS_PERMITIDOS, "effect": "deny"},
        {"capability": "fs_write", "match": SEGREDOS + extras, "effect": "deny"},
        {"capability": "shell", "match": SHELL_IMPRIME, "effect": "deny"},
    ]
    if papel is None:
        return {"name": NOME, "description": "Perfil gerado pela Forja: bloqueia leitura de segredos (gerado automaticamente; nao edite).",
                "tools": ["read", "write", "shell", "web", "@forja"], "permissions": {"rules": regras}, "prompt": ESCOPO}
    p = PAPEIS[papel]
    return {"name": nome_papel(papel), "description": f"Perfil Forja ({p['descricao']}); bloqueia segredos. Gerado automaticamente; nao edite.",
            "tools": list(p["tools"]), "permissions": {"rules": regras}, "prompt": f"{ESCOPO}\n{p['prompt']}"}


def garantir(pasta_agentes: Path | None = None, protegidas: list[Path] | None = None) -> Path:
    """Grava (ou mantem) ~/.kiro/agents/forja.json e um perfil por papel (forja-planejador, forja-executor...). Todos com as
    mesmas regras DENY de segredos. Idempotente: so reescreve o que mudou."""
    pasta = pasta_agentes or (Path.home() / ".kiro" / "agents")
    pasta.mkdir(parents=True, exist_ok=True)
    base = pasta / f"{NOME}.json"
    for papel in (None, *PAPEIS):
        arq = pasta / f"{NOME if papel is None else nome_papel(papel)}.json"
        conteudo = json.dumps(montar(protegidas, papel), ensure_ascii=False, indent=1)
        if not arq.is_file() or arq.read_text(encoding="utf-8") != conteudo:
            arq.write_text(conteudo, encoding="utf-8")
            log.info("perfil de agente do Kiro atualizado", extra={"evento": "kiro.perfil_gravado", "caminho": arq.name})
    return base
