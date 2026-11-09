"""agenda.ler_ics: eventos de um arquivo iCalendar (.ics) local, por periodo. Sem rede e sem credenciais.

Para usar sua agenda sem custo: exporte (Google, Outlook, Apple) para .ics e aponte para o arquivo.
Recorrencias (RRULE) NAO sao expandidas: o evento base e listado e marcado como recorrente.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from forja.dominio.erros import ValidacaoDominio
from forja.ferramentas.caminhos import resolver_dentro
from forja.ferramentas.contrato import ResultadoFerramenta, montar

MAX_BYTES = 2_000_000
MAX_EVENTOS = 500
_DT = re.compile(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?)?Z?$")


def _desdobrar(texto: str) -> list[str]:
    """RFC 5545: linha que comeca com espaco/tab continua a anterior."""
    saida: list[str] = []
    for ln in texto.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if ln[:1] in (" ", "\t") and saida:
            saida[-1] += ln[1:]
        else:
            saida.append(ln)
    return saida


def _data(valor: str) -> datetime | None:
    m = _DT.match(valor.strip())
    if not m:
        return None
    a, mo, d, h, mi, s = m.groups()
    try:
        return datetime(int(a), int(mo), int(d), int(h or 0), int(mi or 0), int(s or 0))
    except ValueError:
        return None


def _desescapar(v: str) -> str:
    return v.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def parse_ics(texto: str) -> list[dict]:
    eventos: list[dict] = []
    atual: dict | None = None
    for ln in _desdobrar(texto):
        if ln == "BEGIN:VEVENT":
            atual = {}
        elif ln == "END:VEVENT" and atual is not None:
            if atual.get("inicio"):
                eventos.append(atual)
            atual = None
        elif atual is not None and ":" in ln:
            chave, valor = ln.split(":", 1)
            nome = chave.split(";", 1)[0].upper()
            if nome == "SUMMARY":
                atual["titulo"] = _desescapar(valor)[:200]
            elif nome == "LOCATION":
                atual["local"] = _desescapar(valor)[:200]
            elif nome == "DTSTART":
                atual["inicio"] = _data(valor)
                atual["dia_inteiro"] = "VALUE=DATE" in chave.upper() and "T" not in valor
            elif nome == "DTEND":
                atual["fim"] = _data(valor)
            elif nome == "RRULE":
                atual["recorrente"] = True
    return eventos


def ler_agenda(raiz: Path, caminho: str, de: str = "", ate: str = "", limite: int = 50) -> ResultadoFerramenta:
    if not 1 <= limite <= MAX_EVENTOS:
        raise ValidacaoDominio(f"limite deve estar entre 1 e {MAX_EVENTOS}")
    real = resolver_dentro(raiz, caminho)
    if real.suffix.lower() != ".ics":
        raise ValidacaoDominio("esperado um arquivo .ics")
    if real.stat().st_size > MAX_BYTES:
        raise ValidacaoDominio("arquivo .ics acima do limite de tamanho")
    texto = real.read_text(encoding="utf-8", errors="replace")
    return resumir_eventos(texto, de, ate, limite, "agenda.ler_ics")


def resumir_eventos(texto: str, de: str, ate: str, limite: int, ferramenta: str) -> ResultadoFerramenta:
    """Resumo de eventos de um texto .ics (arquivo local ou baixado por URL). `de`/`ate` em ISO."""
    if not 1 <= limite <= MAX_EVENTOS:
        raise ValidacaoDominio(f"limite deve estar entre 1 e {MAX_EVENTOS}")
    try:
        ini = datetime.fromisoformat(de) if de else None
        fim = datetime.fromisoformat(ate) if ate else None
    except ValueError as e:
        raise ValidacaoDominio("de/ate devem estar em ISO (YYYY-MM-DD)") from e
    todos = parse_ics(texto)
    no_periodo = [e for e in todos if (not ini or e["inicio"] >= ini) and (not fim or e["inicio"] <= fim)]
    no_periodo.sort(key=lambda e: e["inicio"])
    corte = no_periodo[:limite]
    linhas = [f"{len(no_periodo)} evento(s) no periodo (de {len(todos)} no arquivo)"]
    for e in corte:
        quando = e["inicio"].date().isoformat() if e["dia_inteiro"] else e["inicio"].strftime("%Y-%m-%d %H:%M")
        extra = (" | " + e["local"] if e.get("local") else "") + (" | recorrente (nao expandido)" if e.get("recorrente") else "")
        linhas.append(f"- {quando} {e.get('titulo', '(sem titulo)')}{extra}")
    dados = {"total_arquivo": len(todos), "total_periodo": len(no_periodo),
             "eventos": [{"inicio": e["inicio"].isoformat(), "dia_inteiro": e["dia_inteiro"],
                          "titulo": e.get("titulo", ""), "local": e.get("local", ""),
                          "recorrente": bool(e.get("recorrente"))} for e in corte]}
    avisos = ["fusos horarios sao ignorados: horarios lidos como escritos no arquivo"]
    return montar(ferramenta, texto, "\n".join(linhas), dados, len(no_periodo) > len(corte), avisos)
