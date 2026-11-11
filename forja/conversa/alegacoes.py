"""Salvaguarda anti-alucinacao DETERMINISTICA: confere alegacoes da resposta do agente contra o que a Forja OBSERVOU.

Agentes de codigo costumam afirmar "os testes passaram" ou "criei X" sem ter feito. Aqui nada e julgado por LLM:
- testes: "testes passaram/verdes/ok" exige um comando de teste OBSERVADO e concluido (tool_call de execucao);
- comandos: "rodei/executei ..." exige alguma execucao concluida;
- arquivos: "criei/alterei `a.py`" exige escrita concluida e o arquivo existente; "removi `a.py`" exige que ele nao exista;
- citacoes: caminhos relativos entre crases que nao existem na pasta de trabalho sao sinalizados (podem ser inventados).
Frases negadas ("nao rodei os testes") nao contam como alegacao. O resultado so SINALIZA; nao altera a resposta.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MAX_ALEGACOES = 12
_NEGACAO = re.compile(r"\b(n[aã]o|nunca|sem|nem|ainda n[aã]o|faltou|falta)\b[^.\n]{0,25}$", re.IGNORECASE)
_TESTES = re.compile(
    r"\b(testes?|pytest|su[ií]te|vitest|jest|unittest|cobertura)\b[^.\n]{0,60}?\b(passa(m|ram|ndo)?|passou|verdes?|ok|sucesso|aprovad[oa]s?)\b",
    re.IGNORECASE)
_RODEI = re.compile(r"\b(rodei|executei|rodamos|executamos|rodando o comando|ao rodar)\b", re.IGNORECASE)
_ARQ = r"`([^`\s*?<>|]+\.[A-Za-z0-9]{1,8})`"
_ESCREVI = re.compile(r"\b(criei|alterei|editei|modifiquei|atualizei|ajustei|corrigi|adicionei)\b[^\n]{0,80}?" + _ARQ, re.IGNORECASE)
_REMOVI = re.compile(r"\b(removi|apaguei|exclu[ií])\b[^\n]{0,80}?" + _ARQ, re.IGNORECASE)
_CITADO = re.compile(r"`((?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,8})`")
_CMD_TESTE = re.compile(r"\b(pytest|unittest|tox|nox|jest|vitest|mocha|go test|cargo test|dotnet test|mvn\b.*test|gradle\w*\b.*test|"
                        r"(npm|pnpm|yarn|bun)( run)? test|make test|phpunit|rspec)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Alegacao:
    tipo: str  # testes | comando | arquivo_escrito | arquivo_removido | arquivo_citado
    trecho: str
    verificada: bool
    motivo: str

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


def _negada(texto: str, inicio: int) -> bool:
    return bool(_NEGACAO.search(texto[max(0, inicio - 40):inicio]))


def _trecho(texto: str, m: re.Match) -> str:
    return " ".join(texto[m.start():m.end()].split())[:160]


def _concluidas(ferramentas: list[dict[str, Any]], *tipos: str) -> list[dict[str, Any]]:
    return [f for f in ferramentas if f.get("status") == "completed" and (f.get("tipo") in tipos)]


def _existe(cwd: Path | None, rel: str) -> bool | None:
    """None = nao da para conferir (sem pasta, caminho absoluto ou fora da pasta)."""
    if cwd is None or rel.startswith(("/", "\\", "~")) or re.match(r"^[A-Za-z]:", rel) or ".." in Path(rel).parts:
        return None
    try:
        return (cwd / rel).exists()
    except OSError:
        return None


def verificar(texto: str, ferramentas: list[dict[str, Any]], cwd: Path | None = None) -> list[Alegacao]:
    """`ferramentas`: tool_calls observados [{tipo: read|edit|delete|execute|..., status, titulo, comando}]."""
    saida: list[Alegacao] = []
    execucoes = _concluidas(ferramentas, "execute")
    escritas = _concluidas(ferramentas, "edit", "delete", "move")

    for m in _TESTES.finditer(texto):
        if _negada(texto, m.start()) or any(a.tipo == "testes" for a in saida):
            continue
        testes = [f for f in execucoes if _CMD_TESTE.search(f"{f.get('comando') or ''} {f.get('titulo') or ''}")]
        if testes:
            saida.append(Alegacao("testes", _trecho(texto, m), True, "comando de teste observado e concluido"))
        elif execucoes:
            saida.append(Alegacao("testes", _trecho(texto, m), False, "houve execucao, mas nenhum comando de teste foi reconhecido"))
        else:
            saida.append(Alegacao("testes", _trecho(texto, m), False, "nenhum comando foi executado nesta execucao"))

    for m in _RODEI.finditer(texto):
        if not _negada(texto, m.start()) and not execucoes:
            saida.append(Alegacao("comando", _trecho(texto, m), False, "nenhuma execucao de comando foi observada"))
            break

    vistos: set[str] = set()
    for m in _ESCREVI.finditer(texto):
        arq = m.group(2)
        if arq in vistos or _negada(texto, m.start()):
            continue
        vistos.add(arq)
        existe = _existe(cwd, arq)
        if not escritas:
            saida.append(Alegacao("arquivo_escrito", _trecho(texto, m), False, "nenhuma escrita de arquivo foi observada"))
        elif existe is False:
            saida.append(Alegacao("arquivo_escrito", _trecho(texto, m), False, f"{arq} nao existe na pasta de trabalho"))
    for m in _REMOVI.finditer(texto):
        arq = m.group(2)
        if arq in vistos or _negada(texto, m.start()):
            continue
        vistos.add(arq)
        if _existe(cwd, arq) is True:
            saida.append(Alegacao("arquivo_removido", _trecho(texto, m), False, f"{arq} ainda existe na pasta de trabalho"))
    for m in _CITADO.finditer(texto):
        arq = m.group(1)
        if arq in vistos:
            continue
        vistos.add(arq)
        if _existe(cwd, arq) is False:
            saida.append(Alegacao("arquivo_citado", arq, False, "caminho citado nao existe na pasta de trabalho"))
    return saida[:MAX_ALEGACOES]


def resumo(alegacoes: list[Alegacao]) -> str:
    """Texto curto para a conversa. Vazio se nao ha nada a sinalizar."""
    falhas = [a for a in alegacoes if not a.verificada]
    if not falhas:
        return ""
    return "A Forja não conseguiu confirmar estas afirmações da resposta (confira antes de confiar):\n" + "\n".join(
        f"- \u201c{a.trecho}\u201d: {a.motivo}." for a in falhas)
