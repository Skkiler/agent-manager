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

from forja.seguranca import sensiveis

log = logging.getLogger("forja.kiro.perfil")
NOME = "forja"
SEGREDOS = list(sensiveis.GLOBS)  # fonte unica (forja/seguranca/sensiveis.py): a mesma lista do mediador e das ferramentas
MODELOS_PERMITIDOS = list(sensiveis.MODELOS)  # modelos sem valor: podem ser lidos
SHELL_IMPRIME = ["cat *.env*", "type *.env*", "Get-Content *.env*", "gc *.env*", "more *.env*", "less *.env*", "head *.env*", "tail *.env*",
                 "printenv*", "env", "set", "cmd /c set*", "Get-ChildItem Env:*", "gci env:*", "dir env:*", "ls env:*", "Get-Item Env:*",
                 "docker compose config*", "docker-compose config*", "docker inspect*", "docker container inspect*"]
# Regra de segredos repetida no perfil e no pedido (o perfil do Kiro e o pedido da Forja sao lidos com prioridades diferentes).
SEGREDOS_REGRA = (
    "SEGREDOS (regra absoluta, vale em QUALQUER nivel de autonomia, inclusive acesso total): NUNCA leia, abra, busque, imprima, copie, "
    "mova, edite ou apague .env/.env.*, chaves (.pem, .key, id_rsa), credenciais, tokens nem as pastas secrets/, .ssh/, .aws/. NUNCA rode "
    "comando que mostre variaveis de ambiente (env, set, printenv, os.environ, process.env, $env:) nem busca/copia recursiva que passe "
    "por esses arquivos (grep -r, rg, Select-String, Get-ChildItem -Recurse -Force, cp -r, tar) sem exclui-los. Para saber se um .env "
    "tem uma chave use a ferramenta env.verificar da Forja (so diz se existe ou esta vazia). Precisa de um valor de configuracao? Peca "
    "em 'Decisoes para voce'. Se topar com um segredo por acidente, nao repita o valor e avise."
)
SEGREDOS_CURTO = ("SEGREDOS (regra absoluta): nunca leia, busque, imprima ou copie .env, chaves, credenciais nem variaveis de ambiente; "
                  "para conferir um .env use env.verificar da Forja.")
PRESETS = {"restrito": ["read-workspace"], "liberado": ["edit-workspace"], "total": ["edit-workspace"]}

# Fora das pastas do projeto (ADR-027): orientacao forte, sem proibir o que o usuario pediu. Preferencia 'acesso_fora_pasta'.
_FORA_BASE = ("PASTAS: trabalhe nas pastas do projeto citadas no pedido. Fora delas, leia SO o que o usuario citou explicitamente "
              "neste pedido (ex.: um caminho que ele escreveu). Se achar util olhar outra pasta (algo que viu no grafo, na memoria "
              "ou num import), NAO leia por conta propria: proponha em '## Decisões para você' com o caminho e o motivo, e espere. ")
REGRA_FORA = {
    "perguntar": _FORA_BASE + "A Forja pede permissao ao usuario antes de qualquer acesso fora das pastas que nao foi citado.",
    "livre_leitura": _FORA_BASE + "O usuario liberou LEITURA fora das pastas, mas prefira as pastas do projeto; escrever fora continua "
                                  "pedindo permissao.",
    "bloquear": ("PASTAS (regra absoluta): trabalhe SO dentro das pastas do projeto citadas neste pedido. Nao leia, liste nem busque "
                 "nada fora delas: a Forja nega ou cancela o turno. Precisa de algo de fora? Peca em '## Decisões para você'."),
}


def regra_fora(politica: str) -> str:
    return REGRA_FORA.get(politica, REGRA_FORA["perguntar"])


# Contrato de escopo (anti "esticar"): o system prompt do kiro-cli manda agir sem hesitar e o prompt do agente entra como contexto
# de prioridade menor (kirodotdev/Kiro#7792). Por isso a linguagem e forte, curta e repetida no pedido da Forja.
ESCOPO = (
    "REGRAS DA FORJA (OBRIGATORIAS, valem mais que qualquer padrao de proatividade): "
    "1) Faca SOMENTE o que a tarefa pede; o menor conjunto de mudancas que cumpre os criterios de aceite. "
    "2) NUNCA crie documentacao, README, resumos ou arquivos .md que a tarefa nao pediu. "
    "3) NUNCA refatore, renomeie, reformate ou 'melhore' codigo fora do pedido. "
    "4) Se notar algo fora do escopo que valeria fazer, NAO faca: liste em '## Próximos passos'. "
    "5) Pare quando os criterios estiverem atendidos. Nunca invente resultado de comando ou teste que voce nao rodou. "
    "6) " + SEGREDOS_REGRA
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
