"""testes.resumir_saida: reduz a saida do pytest a veredito, contagens e causa de cada falha."""

from __future__ import annotations

import re

from forja.ferramentas.contrato import ResultadoFerramenta, montar

MAX_FALHAS = 10
MAX_LINHAS_ERRO = 4
MAX_COLUNAS = 220

_CABECALHO = re.compile(r"^_{3,} (?P<nome>.+?) _{3,}$")
_RODAPE = re.compile(r"^=+ (?P<corpo>.*?\b(?:passed|failed|error|errors|skipped|deselected|no tests ran)\b.*?) =+$")
_CONTAGEM = re.compile(r"(\d+) (passed|failed|errors?|skipped|deselected|xfailed|xpassed|warnings?)")
_LOCAL = re.compile(r"^(?P<arq>[^\s:]+\.py):(?P<linha>\d+): ")
_RESUMO_FALHA = re.compile(r"^(?P<tipo>FAILED|ERROR) (?P<id>\S+)(?: - (?P<msg>.*))?$")
_TEMPO = re.compile(r"in (\d+(?:\.\d+)?)s")
_NORMAL = {"error": "errors", "warning": "warnings"}


def _curta(s: str) -> str:
    return s if len(s) <= MAX_COLUNAS else s[: MAX_COLUNAS - 3] + "..."


def resumir_pytest(saida: str, limite: int = MAX_FALHAS) -> ResultadoFerramenta:
    linhas = saida.splitlines()
    contagens: dict[str, int] = {}
    tempo = None
    for ln in reversed(linhas):  # o rodape (ou a linha -q) fica no fim
        corpo = _RODAPE.match(ln.strip())
        texto = corpo.group("corpo") if corpo else ln.strip()
        achados = _CONTAGEM.findall(texto)
        if achados and (corpo or _TEMPO.search(texto)):
            contagens = {_NORMAL.get(k, k): int(n) for n, k in achados}
            m = _TEMPO.search(texto)
            tempo = float(m.group(1)) if m else None
            break

    blocos: dict[str, dict] = {}
    atual = None
    for ln in linhas:
        cab = _CABECALHO.match(ln.strip())
        if cab:
            atual = cab.group("nome")
            blocos[atual] = {"erros": [], "local": None}
            continue
        if ln.startswith("=") and not _CABECALHO.match(ln):
            atual = None
        if atual is None:
            continue
        if ln.startswith("E ") or ln.startswith("E\t"):
            if len(blocos[atual]["erros"]) < MAX_LINHAS_ERRO:
                blocos[atual]["erros"].append(_curta(ln[1:].strip()))
        else:
            loc = _LOCAL.match(ln.strip())
            if loc:
                blocos[atual]["local"] = f"{loc.group('arq')}:{loc.group('linha')}"

    falhas = []
    for ln in linhas:
        m = _RESUMO_FALHA.match(ln.strip())
        if m:
            falhas.append({"id": m.group("id"), "tipo": m.group("tipo"), "msg": _curta(m.group("msg") or "")})

    ok = bool(contagens) and not contagens.get("failed") and not contagens.get("errors")
    veredito = "SEM_RESULTADO" if not contagens else ("APROVADO" if ok else "REPROVADO")
    partes = ", ".join(f"{n} {k}" for k, n in contagens.items())
    saida_txt = [f"{veredito}: {partes or 'rodape do pytest nao encontrado'}" + (f" em {tempo}s" if tempo else "")]
    detalhes = []
    for f in falhas[:limite]:
        nome_curto = f["id"].split("::", 1)[-1]
        bloco = next((b for n, b in blocos.items() if n and (n == nome_curto or nome_curto.endswith(n))), None)
        linha = f"- {f['id']}"
        if bloco and bloco["local"]:
            linha += f" @ {bloco['local']}"
        causa = (bloco["erros"] if bloco and bloco["erros"] else [f["msg"]] if f["msg"] else [])
        detalhes.append(linha + "".join(f"\n    {c}" for c in causa))
    saida_txt += detalhes
    omitidas = max(0, len(falhas) - limite)
    if omitidas:
        saida_txt.append(f"(+{omitidas} falhas omitidas)")
    avisos = [] if contagens else ["nao encontrei a linha final do pytest; verifique a execucao"]
    if contagens and (contagens.get("failed", 0) + contagens.get("errors", 0)) > len(falhas):
        avisos.append("ha falhas sem linha 'FAILED' (use -rfE); detalhes incompletos")
    dados = {"veredito": veredito, "contagens": contagens, "segundos": tempo, "falhas": falhas[:limite]}
    return montar("testes.resumir_saida", saida, "\n".join(saida_txt), dados, omitidas > 0, avisos)
