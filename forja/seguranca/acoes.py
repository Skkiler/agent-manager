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

MAX_ALVOS = 6
MAX_CMD = 200
RISCOS = ("baixo", "medio", "alto", "critico")

_SENSIVEL = re.compile(
    r"(^|[\\/])(\.env(\..*)?|.*\.(pem|key|p12|pfx|jks|kdbx)|id_(rsa|ed25519)\S*|credentials(\.json)?|"
    r"secrets?(\.(json|ya?ml))?|api_token\.txt|\.netrc|\.npmrc|\.pypirc)$",
    re.IGNORECASE,
)
_RM = re.compile(r"(?i)(^|[\s;&|])(rm|rmdir|rd|del|erase|remove-item|ri)(\s|$)")
_FORCA = re.compile(r"(?i)(\s-[a-z]*[rf][a-z]*\b|\s-force\b|\s-recurse\b|\s/[sq]\b|\s--force\b|\s--recursive\b)")
_PUSH = re.compile(
    r"(?i)\bgit\s+push\b|\bgh\s+(pr|release|repo)\s+(create|merge|delete)\b|\bnpm\s+publish\b|\btwine\s+upload\b")
_DESCARTA = re.compile(r"(?i)\bgit\s+(reset\s+--hard|clean\s+-\w*f|checkout\s+--\s|restore\s+\.|stash\s+drop)")
_INSTALA = re.compile(
    r"(?i)\b(pip3?|uv|npm|pnpm|yarn|winget|choco|scoop|cargo|gem|apt(-get)?|brew)\s+(install|add|i)\b")
_REDE = re.compile(r"(?i)\b(curl|wget|invoke-webrequest|iwr|invoke-restmethod|irm|ssh|scp|ftp)\b")
_MOVE = re.compile(r"(?i)(^|[\s;&|])(mv|move|ren|rename|move-item)(\s|$)")

_CAMPOS_CAMINHO = (
    "path", "file_path", "filePath", "filepath", "file", "target", "dest", "destination", "directory", "dir")


def _comando(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    for k in ("command", "cmd", "script"):
        v = raw.get(k)
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            return " ".join(str(x) for x in v)
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
        alvo = Path(caminho)
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


def descrever_acao(tool_call: dict[str, Any], workspace: Path | None = None) -> dict[str, Any]:
    """Retorna {id, categoria, risco, descricao, alvos, sensivel, fora_do_workspace, tecnico}."""
    tc = tool_call or {}
    kind = str(tc.get("kind") or "").lower()
    titulo = sanitizar_texto(str(tc.get("title") or ""))[:120]
    cmd = _comando(tc.get("rawInput")).strip()
    alvos = _caminhos(tc)
    categoria, risco = "outra", "medio"

    if cmd and _RM.search(cmd):
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
    elif cmd and _REDE.search(cmd):
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

    candidatos = alvos + [t.strip("\"';,()") for t in re.split(r"\s+", cmd) if t]  # cada token do comando conta
    sensivel = any(_SENSIVEL.search(c.replace("\\", "/")) for c in candidatos)
    fora = any(_fora_do_workspace(a, workspace) for a in alvos)  # avaliado ANTES de relativizar
    alvos = _normalizar(alvos, workspace)
    if sensivel:
        risco = "critico"
    elif fora and RISCOS.index(risco) < RISCOS.index("alto"):
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
        "executar_comando": f"Posso executar o comando `{cmd_vis or titulo}`?",
        "modificar_arquivos": f"Posso criar ou modificar {_lista(alvos)}?",
        "ler": f"Posso ler {_lista(alvos)}?",
        "outra": f"Posso executar a ação «{titulo or 'não identificada'}»?",
    }
    return {
        "id": str(tc.get("toolCallId") or titulo),
        "categoria": categoria,
        "risco": risco,
        "descricao": frases[categoria],
        "alvos": [sanitizar_texto(a)[:200] for a in alvos[:MAX_ALVOS]],
        "sensivel": sensivel,
        "fora_do_workspace": fora,
        "tecnico": titulo,
    }
