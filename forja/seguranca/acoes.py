"""Traduz uma chamada de ferramenta bruta em uma ACAO compreensivel ("Posso excluir forcadamente ...?").

Puro e deterministico (sem I/O alem de normalizar caminhos). Serve a aprovacao por acao, nao por comando.
Acoes que tocam segredos sao marcadas `sensivel` e NUNCA entram em um pedido aprovavel: sao negadas antes.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

from forja.observabilidade.sanitizar import sanitizar_texto
from forja.seguranca import sensiveis

MAX_ALVOS = 6
MAX_CMD = 200
RISCOS = ("baixo", "medio", "alto", "critico")

_RM = re.compile(r"(?i)(^|[\s;&|])(rm|rmdir|rd|del|erase|remove-item|ri)(\s|$)")
_FORCA = re.compile(r"(?i)(\s-[a-z]*[rf][a-z]*\b|\s-force\b|\s-recurse\b|\s/[sq]\b|\s--force\b|\s--recursive\b)")
_PUSH = re.compile(
    r"(?i)\bgit\s+push\b|\bgh\s+(pr|release|repo)\s+(create|merge|delete)\b|\bnpm\s+publish\b|\btwine\s+upload\b")
_DESCARTA = re.compile(r"(?i)\bgit\s+(reset\s+--hard|clean\s+-\w*f|checkout\s+--\s|restore\s+\.|stash\s+drop)")
_INSTALA = re.compile(
    r"(?i)\b(pip3?|uv|npm|pnpm|yarn|winget|choco|scoop|cargo|gem|apt(-get)?|brew)\s+(install|add|i)\b")
_REDE = re.compile(r"(?i)\b(curl|wget|invoke-webrequest|iwr|invoke-restmethod|irm|ssh|scp|ftp)\b(?![./\\])")
# Abre uma porta para a rede (servidor local exposto): sempre pergunta, como acesso a rede.
_ESCUTA = re.compile(
    r"(?i)\bhttp\.server\b|\bSimpleHTTPServer\b|\bnpx\s+(http-)?serve\b|\bngrok\b|\b(nc|ncat|netcat)\s+(-\w+\s+)*-\w*l|\bsocat\b"
    r"|--host[= ]0\.0\.0\.0|\bNew-NetFirewallRule\b|\bnetsh\s+advfirewall\b")
# Comando ofuscado ou que executa texto decodificado: nao da para descrever a acao -> sempre pergunta (risco alto).
_OFUSCADO = re.compile(
    r"(?i)\s-(e|ec|enc|encodedcommand)\s+[A-Za-z0-9+/=]{8,}|\binvoke-expression\b|(^|[\s;|&(])iex(\s|\(|$)|FromBase64String"
    r"|\bbase64\s+(-d|--decode)\b|\bcertutil\s+-decode\b|\|\s*(sh|bash|zsh|pwsh|powershell)(\s|$)")
# Varredura ampla: le o CONTEUDO (ou copia) de muitos arquivos de uma vez, inclusive ocultos. Numa pasta com .env, um comando
# assim le o segredo sem nunca citar o nome do arquivo (achado no Kiro real: Get-ChildItem -Recurse -Force | Select-String).
_VARREDURA = re.compile(
    r"(?i)\bselect-string\b|(^|[\s;|&(])sls\s|\b(grep|egrep|fgrep)\s+(-\w*\s+)*-\w*[rR]|\bgrep\s+--recursive\b|(^|[\s;|&(])(rg|ag|ack)\s"
    r"|\bfindstr\b.*\s/s\b|\bfind\b.*\s-(exec|print0)\b|\bxargs\b"
    r"|\b(cat|type|get-content|gc|more|less|head|tail)\s+(\S+\s+)*\S*[*?]"
    r"|\b(get-childitem|gci|dir|ls)\b.*\s-(r|recurse|force)\b.*\|\s*(%|foreach|select-string|get-content|gc|cat|type)"
    r"|\b(tar|zip|7z|compress-archive|robocopy|xcopy)\b|\b(cp|copy-item|copy)\b.*\s-(r|recurse)\b")
_MOVE = re.compile(r"(?i)(^|[\s;&|])(mv|move|ren|rename|move-item)(\s|$)")

# Ferramentas do MCP da propria Forja (o Kiro intitula @forja/<nome> e marca _meta.kiro.serverName).
_FORJA_MCP = {
    "forja_listar_ferramentas": "consultar quais ferramentas da Forja estão disponíveis",
    "forja_executar_ferramenta": "usar uma ferramenta de leitura da Forja",
    "forja_buscar_memoria": "buscar no seu segundo cérebro",
    "forja_quadro_ler": "ler as mensagens do quadro endereçadas a ele",
    "forja_quadro_publicar": "publicar uma mensagem no quadro",
    "forja_navegar_memoria": "abrir um tópico do seu segundo cérebro",
    "forja_propor_nota": "propor uma nota candidata para você revisar",
    "forja_caderno_salvar": "anotar no caderno desta tarefa o que já resolveu",
    "forja_caderno_consultar": "consultar o caderno desta tarefa",
}


def _ferramenta_forja(tc: dict[str, Any]) -> str | None:
    servidor = (((tc.get("_meta") or {}).get("kiro") or {}).get("serverName") or "")
    titulo = str(tc.get("title") or "")
    nome = titulo.removeprefix("@forja/") if titulo.startswith("@forja/") else (titulo if servidor == "forja" else "")
    return nome if nome in _FORJA_MCP else None


# Usar um .env sem le-lo: programas que recebem o arquivo e o consomem (subir containers, rodar com variaveis).
_CONSOME_ENV = re.compile(r"(?i)^\s*(docker(\s+compose)?|docker-compose|podman(-compose)?|uv\s+run|dotenv\s+(-f\s+\S+\s+)?run)\b.*--?env-file(\s|=)")
# ...e os que IMPRIMEM variaveis resolvidas (mesmo sem citar o arquivo): sempre tratados como leitura de segredo.
# Nome de variavel com cara de segredo (para $NOME, ${NOME} e %NOME%): $_ e variaveis comuns do PowerShell NAO contam.
_NOME_SEGREDO = (r"(?:(?:FORJA|APP)_[A-Za-z0-9_]+|[A-Za-z_]*(?:TOKEN|SECRET|PASSW|PASSWD|SENHA|API_?KEY|ACCESS_?KEY|PRIVATE|CRED|AUTH|"
                 r"COOKIE|SESSION)[A-Za-z0-9_]*)")
_IMPRIME_ENV = re.compile(
    r"(?i)(^|[;&|]\s*)(printenv|env|set|export\s+-p|get-childitem\s+env:|gci\s+env:|dir\s+env:|ls\s+env:)(\s*$|\s*[;&|])"
    r"|\bcmd(\.exe)?\s+/c\s+set\b"
    r"|\b(docker(\s+compose)?|docker-compose|podman(-compose)?)\s+(\S+\s+)*config\b"
    r"|\bdocker\s+(container\s+)?inspect\b|\bdocker\s+exec\b.*\b(env|printenv|set)\b|\$\{?env:" + _NOME_SEGREDO +
    r"|\b(get-item|gi|get-content|gc|get-childitem|gci|dir|ls)\s+env:"
    r"|\bos\.environ\b|\bos\.getenv\b|\bgetenv\s*\(|\bprocess\.env\b|\[(system\.)?environment\]::|\bSystem\.getenv\b|\bENV\["
    r"|\$\{?" + _NOME_SEGREDO + r"\}?|%" + _NOME_SEGREDO + "%")
# Caminhos que saem da pasta: absolutos, pasta pessoal e subida de diretorio (o comando pode ler qualquer coisa la).
_ABSOLUTO = re.compile(r"(?i)^([a-z]:[\\/]|\\\\|/[^\s/]+/|~|\$home\b|\$env:(userprofile|home|appdata|localappdata)|%(userprofile|appdata|localappdata|homepath)%)")
_SUBIDA = re.compile(r"(^|[\\/])\.\.([\\/]|$)")


# ".env" em qualquer ponto do texto do comando (modelos .env.example/.sample/.template/.dist nao contam).
_ENV_NO_TEXTO = re.compile(r"(?i)(?<![\w.])\.env(?!\.(example|sample|template|dist)\b)(\.\w+)?(?![\w])")


def _sem_argumento_env_file(tokens: list[str]) -> list[str]:
    saida, pular = [], False
    for t in tokens:
        if pular:
            pular = False
            continue
        if t.lower() in ("--env-file", "-env-file"):
            pular = True
            continue
        if t.lower().startswith(("--env-file=", "-env-file=")):
            continue
        saida.append(t)
    return saida


_CAMPOS_CAMINHO = (
    "path", "file_path", "filePath", "filepath", "file", "target", "dest", "destination", "directory", "dir")


def caminho_sensivel(caminho: str) -> bool:
    """True se o caminho parece segredo/credencial (.env, chaves, tokens). Fonte unica: forja/seguranca/sensiveis.py."""
    return sensiveis.caminho_sensivel(caminho)


def _caminhos_no_comando(tokens: list[str]) -> list[str]:
    """Tokens do comando que sao caminhos para FORA da pasta: absolutos, pasta pessoal (~, $HOME, %USERPROFILE%) ou com '..'.
    O 1o token (o executavel, ex.: C:\\Python313\\python.exe) nao conta: rodar um programa nao e ler dados fora da pasta."""
    saida = []
    for t in tokens[1:]:
        t = t.strip("\"'`;,(){}")
        if "=" in t and not _ABSOLUTO.match(t):  # --opcao=valor: olha o valor
            t = t.split("=", 1)[1].strip("\"'")
        if t and (_ABSOLUTO.match(t) or _SUBIDA.search(t)) and not t.startswith(("http://", "https://")):
            saida.append(t)
    return saida


# Invólucro de shell que alguns agentes poem em volta do comando (codex-acp: "C:\...\powershell.exe" -Command 'python x.py').
_INVOLUCRO = re.compile(r"""(?is)^\s*"?[^"\s]*?(?:powershell|pwsh|cmd|bash|sh|zsh)(?:\.exe)?"?\s+(?:-(?:noprofile|nologo|noninteractive)\s+)*"""
                        r"""(?:-command|-c|/c|-lc)\s+(.+)$""")


def _desembrulhar(cmd: str) -> str:
    m = _INVOLUCRO.match(cmd)
    if not m:
        return cmd
    interno = m.group(1).strip()
    if len(interno) >= 2 and interno[0] == interno[-1] and interno[0] in "'\"":
        interno = interno[1:-1]
    return interno


def _comando(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    for k in ("command", "cmd", "script"):
        v = raw.get(k)
        if isinstance(v, str):
            return _desembrulhar(v)
        if isinstance(v, list):
            return _desembrulhar(" ".join(str(x) for x in v))
    return ""


def _caminhos(tc: dict[str, Any]) -> list[str]:
    achados: list[str] = []
    for loc in tc.get("locations") or []:
        if isinstance(loc, dict) and isinstance(loc.get("path"), str):
            achados.append(loc["path"])
    raw = tc.get("rawInput")
    if isinstance(raw, dict):
        for k in _CAMPOS_CAMINHO:
            v = raw.get(k)
            if isinstance(v, str):
                achados.append(v)
        for k in ("paths", "files"):
            v = raw.get(k)
            if isinstance(v, list):
                achados.extend(str(x) for x in v if isinstance(x, str))
    return achados


caminhos_do_tool_call = _caminhos  # publico: o provedor usa o MESMO extrator do mediador (formato real do Kiro)


def _alvos_do_comando(cmd: str) -> list[str]:
    try:
        tokens = shlex.split(cmd, posix=False)
    except ValueError:
        tokens = cmd.split()
    alvos, viu_verbo = [], False
    for t in tokens:
        baixo = t.lower().strip(";&|")
        if not viu_verbo:
            viu_verbo = bool(_RM.search(" " + baixo + " ")) or baixo in {"mv", "move", "ren", "rename", "move-item"}
            continue
        if t.startswith("-") or (t.startswith("/") and len(t) <= 3) or t in {"&&", ";", "|", "||"}:
            continue
        alvos.append(t.strip("\"';"))
    return alvos


def _fora_do_workspace(caminho: str, workspace: Path | None) -> bool:
    if workspace is None:
        return False
    try:
        base = workspace.resolve()
        # Conservador em qualquer SO: "\" conta como separador (no Linux "..\x" e um nome literal, mas um agente que manda isso
        # esta tentando sair da pasta, e a regra de autonomia depende desta classificacao). Letra de unidade fora do Windows: fora.
        bruto = caminho.replace("\\", "/")
        if re.match(r"^[A-Za-z]:/", bruto) and not re.match(r"^[A-Za-z]:", str(base)):
            return True
        alvo = Path(bruto)
        alvo = alvo if alvo.is_absolute() else base / alvo
        alvo.resolve().relative_to(base)
        return False
    except (ValueError, OSError):
        return True


def _normalizar(alvos: list[str], workspace: Path | None) -> list[str]:
    """Remove duplicatas (locations + rawInput repetem o mesmo caminho) e mostra relativo ao workspace quando dentro."""
    vistos: dict[str, str] = {}
    for a in alvos:
        exibicao = a
        if workspace is not None:
            try:
                exibicao = Path(a).resolve().relative_to(workspace.resolve()).as_posix() if Path(a).is_absolute() else a
            except (ValueError, OSError):
                exibicao = a  # fora do workspace: mantem o caminho completo (e relevante para o risco)
        vistos.setdefault(exibicao.replace("\\", "/").lower(), exibicao)
    return list(vistos.values())


def _lista(alvos: list[str]) -> str:
    if not alvos:
        return "os itens indicados"
    vis = [f"`{sanitizar_texto(a)[:120]}`" for a in alvos[:MAX_ALVOS]]
    extra = f" (+{len(alvos) - MAX_ALVOS})" if len(alvos) > MAX_ALVOS else ""
    return ", ".join(vis) + extra


ESCRITA = frozenset({"modificar_arquivos", "excluir", "excluir_forcado", "mover"})


def _dentro_de_alguma(caminho: str, raizes: list[Path]) -> bool:
    return any(not _fora_do_workspace(caminho, r) for r in raizes)


def descrever_acao(tool_call: dict[str, Any], workspace: Path | None = None, trabalho: list[Path] | None = None,
                   consulta: list[Path] | None = None) -> dict[str, Any]:
    """Retorna {id, categoria, risco, descricao, alvos, sensivel, fora_do_workspace, em_consulta, tecnico}.
    trabalho/consulta: pastas do projeto. Ler vale em ambas; escrever, so nas de trabalho (em_consulta = escrita numa de consulta)."""
    tc = tool_call or {}
    kind = str(tc.get("kind") or "").lower()
    titulo = sanitizar_texto(str(tc.get("title") or ""))[:120]
    cmd = _comando(tc.get("rawInput")).strip()
    alvos = _caminhos(tc)
    categoria, risco = "outra", "medio"
    forja = _ferramenta_forja(tc)

    ofuscado = bool(cmd) and _OFUSCADO.search(cmd) is not None
    if forja:  # a API da Forja continua decidindo (politica de pastas, integracoes); aqui so se descreve a acao
        categoria, risco = "ferramenta_forja", ("medio" if forja == "forja_quadro_publicar" else "baixo")
    elif ofuscado:  # nao da para dizer o que o comando faz: sempre pergunta (categoria 'outra'), risco alto
        categoria, risco = "outra", "alto"
    elif cmd and _RM.search(cmd):
        alvos = alvos or _alvos_do_comando(cmd)
        forcada = bool(_FORCA.search(cmd))
        categoria, risco = ("excluir_forcado", "critico") if forcada else ("excluir", "alto")
    elif cmd and _PUSH.search(cmd):
        categoria, risco = "publicar", "alto"
    elif cmd and _DESCARTA.search(cmd):
        categoria, risco = "descartar_alteracoes", "alto"
    elif cmd and _INSTALA.search(cmd):
        categoria, risco = "instalar_dependencias", "medio"
    elif cmd and _MOVE.search(cmd):
        alvos = alvos or _alvos_do_comando(cmd)
        categoria, risco = "mover", "medio"
    elif cmd and (_REDE.search(cmd) or _ESCUTA.search(cmd)):
        categoria, risco = "acessar_rede", "medio"
    elif cmd or kind == "execute":
        categoria, risco = "executar_comando", "medio"
    elif kind == "delete":
        categoria, risco = "excluir", "alto"
    elif kind == "move":
        categoria, risco = "mover", "medio"
    elif kind == "edit":
        categoria, risco = "modificar_arquivos", "medio"
    elif kind == "fetch":
        categoria, risco = "acessar_rede", "medio"
    elif kind in {"read", "search", "think"}:
        categoria, risco = "ler", "baixo"

    tokens = [t.strip("\"';,()") for t in re.split(r"\s+", cmd) if t]
    usa_env = bool(cmd) and _CONSOME_ENV.search(cmd) is not None
    if usa_env:  # o .env so aparece como argumento de --env-file: e CONSUMIDO pelo programa, nunca impresso
        tokens = _sem_argumento_env_file(tokens)
    candidatos = alvos + [t.strip("`{}") for t in tokens]  # cada token do comando conta
    sensivel = (any(caminho_sensivel(c) for c in candidatos if c)
                or (bool(cmd) and _IMPRIME_ENV.search(cmd) is not None)
                or _ENV_NO_TEXTO.search(" ".join(tokens)) is not None)  # ex.: python -c "open('.env')": o nome colado em outro texto
    raizes_escrita = [r for r in [workspace, *(trabalho or [])] if r is not None]
    raizes_leitura = raizes_escrita + list(consulta or [])
    no_comando = _caminhos_no_comando(tokens) if cmd else []
    if raizes_escrita:  # avaliado ANTES de relativizar
        fora = any(not _dentro_de_alguma(a, raizes_leitura if categoria == "ler" else raizes_escrita) for a in alvos)
        # caminhos citados DENTRO do comando (type C:\...\x, cat ../../y): o comando pode ler/alterar fora da pasta
        fora = fora or any(c.startswith(("~", "$", "%")) or not _dentro_de_alguma(c, raizes_leitura) for c in no_comando)
    else:
        fora = bool(no_comando)
    varredura = bool(cmd) and _VARREDURA.search(cmd) is not None
    em_consulta = categoria in ESCRITA and any(_dentro_de_alguma(a, list(consulta or [])) and not _dentro_de_alguma(a, raizes_escrita) for a in alvos)
    alvos = _normalizar(alvos, workspace)
    if sensivel:
        risco = "critico"
    elif (fora or ofuscado) and RISCOS.index(risco) < RISCOS.index("alto"):
        risco = "alto"

    cmd_vis = sanitizar_texto(cmd)[:MAX_CMD]
    frases = {
        "excluir_forcado": f"Posso excluir forçadamente {_lista(alvos)}?",
        "excluir": f"Posso excluir {_lista(alvos)}?",
        "publicar": f"Posso publicar alterações em um repositório remoto (`{cmd_vis}`)?",
        "descartar_alteracoes": f"Posso descartar alterações locais não salvas (`{cmd_vis}`)?",
        "instalar_dependencias": f"Posso instalar dependências (`{cmd_vis}`)?",
        "mover": f"Posso mover ou renomear {_lista(alvos)}?",
        "acessar_rede": f"Posso acessar a rede ({cmd_vis or _lista(alvos)})?",
        "executar_comando": f"Posso executar o comando `{cmd_vis or titulo}`{' (usa o .env sem exibi-lo)' if usa_env and not sensivel else ''}?",
        "modificar_arquivos": f"Posso criar ou modificar {_lista(alvos)}?",
        "ler": f"Posso ler {_lista(alvos)}?",
        "ferramenta_forja": f"O agente pode {_FORJA_MCP.get(forja or '', 'usar uma ferramenta da Forja')}?",
        "outra": (f"Posso executar um comando que não dá para descrever com segurança (`{cmd_vis}`)?" if ofuscado
                  else f"Posso executar a ação «{titulo or 'não identificada'}»?"),
    }
    return {
        "id": str(tc.get("toolCallId") or titulo),
        "categoria": categoria,
        "risco": risco,
        "descricao": frases[categoria],
        "alvos": [sanitizar_texto(a)[:200] for a in alvos[:MAX_ALVOS]],
        "sensivel": sensivel,
        "fora_do_workspace": fora,
        "em_consulta": em_consulta,
        "usa_env": usa_env and not sensivel,
        "varredura": varredura,  # le/copia muitos arquivos de uma vez: numa pasta com segredos, nunca e automatico
        "ofuscado": ofuscado,
        "tecnico": titulo,
    }
