"""git.diff_analisar: resume um diff unificado (arquivos, linhas, areas tocadas e sinais de risco) sem reenviar o diff."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from forja.ferramentas.contrato import ResultadoFerramenta, montar
from forja.ferramentas.segredos import suspeita
from forja.seguranca.acoes import caminho_sensivel

MAX_ARQUIVOS = 40
MAX_CONTEXTOS = 4
LIMITE_REMOCAO = 200

_ARQ = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$")
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<nova>\d+)(?:,\d+)? @@ ?(?P<ctx>.*)$")
_DEPS = re.compile(r"(^|/)(pyproject\.toml|requirements[^/]*\.txt|package(-lock)?\.json|poetry\.lock|uv\.lock)$")


@dataclass
class _Arq:
    caminho: str
    estado: str = "M"  # M modificado | A novo | D removido | R renomeado | B binario
    origem: str = ""
    add: int = 0
    rem: int = 0
    contextos: list[str] = field(default_factory=list)
    segredos: list[int] = field(default_factory=list)


def _risco(a: _Arq) -> list[str]:
    r = []
    if caminho_sensivel(a.caminho):
        r.append("arquivo sensivel no diff")
    if "migrations/" in a.caminho or a.caminho.endswith(".sql"):
        r.append("migracao/SQL")
    if _DEPS.search(a.caminho):
        r.append("dependencias")
    if a.segredos:
        r.append(f"possivel segredo nas linhas {a.segredos[:5]}")
    if a.rem >= LIMITE_REMOCAO:
        r.append(f"remocao grande ({a.rem} linhas)")
    return r


def resumir_diff(diff: str) -> ResultadoFerramenta:
    arquivos: list[_Arq] = []
    atual: _Arq | None = None
    linha_nova = 0
    for ln in diff.splitlines():
        m = _ARQ.match(ln)
        if m:
            atual = _Arq(m.group("b"))
            if m.group("a") != m.group("b"):
                atual.estado, atual.origem = "R", m.group("a")
            arquivos.append(atual)
            continue
        if atual is None:
            continue
        if ln.startswith("new file mode"):
            atual.estado = "A"
        elif ln.startswith("deleted file mode"):
            atual.estado = "D"
        elif ln.startswith("Binary files") or ln.startswith("GIT binary patch"):
            atual.estado = "B"
        elif (h := _HUNK.match(ln)):
            linha_nova = int(h.group("nova"))
            ctx = h.group("ctx").strip()
            if ctx and ctx not in atual.contextos and len(atual.contextos) < MAX_CONTEXTOS:
                atual.contextos.append(ctx[:80])
        elif ln.startswith("+") and not ln.startswith("+++"):
            atual.add += 1
            if suspeita(ln[1:]):
                atual.segredos.append(linha_nova)
            linha_nova += 1
        elif ln.startswith("-") and not ln.startswith("---"):
            atual.rem += 1
        elif ln.startswith(" "):
            linha_nova += 1

    total_add = sum(a.add for a in arquivos)
    total_rem = sum(a.rem for a in arquivos)
    codigo = [a for a in arquivos if a.caminho.endswith(".py") and not a.caminho.startswith("tests/")]
    testes = [a for a in arquivos if a.caminho.startswith("tests/") or "/tests/" in a.caminho]
    avisos = []
    if codigo and not testes:
        avisos.append("codigo alterado sem alteracao em testes")
    linhas = [f"{len(arquivos)} arquivo(s), +{total_add} -{total_rem}"]
    for a in arquivos[:MAX_ARQUIVOS]:
        nome = f"{a.origem} -> {a.caminho}" if a.estado == "R" else a.caminho
        linha = f"{a.estado} {nome} +{a.add} -{a.rem}"
        if a.contextos:
            linha += " | " + "; ".join(a.contextos)
        riscos = _risco(a)
        if riscos:
            linha += " | RISCO: " + ", ".join(riscos)
        linhas.append(linha)
    omitidos = max(0, len(arquivos) - MAX_ARQUIVOS)
    if omitidos:
        linhas.append(f"(+{omitidos} arquivos omitidos)")
    linhas += [f"AVISO: {x}" for x in avisos]
    dados = {
        "arquivos": [
            {"caminho": a.caminho, "estado": a.estado, "adicoes": a.add, "remocoes": a.rem, "riscos": _risco(a)}
            for a in arquivos[:MAX_ARQUIVOS]
        ],
        "adicoes": total_add,
        "remocoes": total_rem,
    }
    return montar("git.diff_analisar", diff, "\n".join(linhas), dados, omitidos > 0, avisos)
