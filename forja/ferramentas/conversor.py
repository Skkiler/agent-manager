"""dados.converter: json <-> jsonl <-> csv <-> tabela markdown. Conversao exata e deterministica (nao e resumo)."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from forja.dominio.erros import ValidacaoDominio
from forja.ferramentas.contrato import ResultadoFerramenta, montar

FORMATOS = ("json", "jsonl", "csv", "md")
MAX_LINHAS = 5000
MAX_SAIDA = 60_000
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _ler(texto: str, formato: str, delimitador: str) -> list[dict[str, Any]]:
    try:
        if formato == "json":
            dados = json.loads(texto)
            if isinstance(dados, dict):
                dados = [dados]
            linhas = dados
        elif formato == "jsonl":
            linhas = [json.loads(ln) for ln in texto.splitlines() if ln.strip()]
        elif formato == "csv":
            linhas = list(csv.DictReader(io.StringIO(texto), delimiter=delimitador))
        else:  # md
            linhas = _ler_md(texto)
    except (ValueError, csv.Error) as e:
        raise ValidacaoDominio(f"entrada {formato} invalida: {str(e)[:120]}") from e
    if not isinstance(linhas, list) or not all(isinstance(x, dict) for x in linhas):
        raise ValidacaoDominio("esperado uma lista de objetos (registros)")
    if len(linhas) > MAX_LINHAS:
        raise ValidacaoDominio(f"mais de {MAX_LINHAS} registros")
    return linhas


def _celulas(ln: str) -> list[str]:
    cru = ln.strip().strip("|").replace("\\|", "\x00")  # "\|" e uma barra literal dentro da celula
    return [c.strip().replace("\x00", "|") for c in cru.split("|")]


def _ler_md(texto: str) -> list[dict[str, Any]]:
    tabela = [ln for ln in texto.splitlines() if ln.strip().startswith("|")]
    if len(tabela) < 2:
        raise ValueError("tabela markdown precisa de cabecalho e separador")
    cab = _celulas(tabela[0])
    return [dict(zip(cab, _celulas(ln), strict=False)) for ln in tabela[2:]]


def _colunas(linhas: list[dict[str, Any]]) -> list[str]:
    cols: list[str] = []
    for ln in linhas:
        for k in ln:
            if k not in cols:
                cols.append(k)
    return cols


def _texto(v: Any) -> str:
    return "" if v is None else (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))


def _escrever(linhas: list[dict[str, Any]], formato: str, delimitador: str, neutralizar: bool) -> tuple[str, int]:
    neutralizadas = 0
    if formato == "json":
        return json.dumps(linhas, ensure_ascii=False, indent=2), 0
    if formato == "jsonl":
        return "\n".join(json.dumps(x, ensure_ascii=False) for x in linhas), 0
    cols = _colunas(linhas)
    if formato == "md":
        esc = lambda s: _texto(s).replace("|", "\\|").replace("\n", " ")  # noqa: E731
        corpo = ["| " + " | ".join(esc(c) for c in cols) + " |", "|" + "|".join(" --- " for _ in cols) + "|"]
        corpo += ["| " + " | ".join(esc(ln.get(c)) for c in cols) + " |" for ln in linhas]
        return "\n".join(corpo), 0
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimitador, lineterminator="\n")
    w.writerow(cols)
    for ln in linhas:
        row = []
        for c in cols:
            v = _texto(ln.get(c))
            if neutralizar and v.startswith(_FORMULA):  # CSV injection: planilhas executam =, +, -, @ no inicio
                v, neutralizadas = "'" + v, neutralizadas + 1
            row.append(v)
        w.writerow(row)
    return buf.getvalue(), neutralizadas


def converter(texto: str, de: str, para: str, delimitador: str = ",", neutralizar_formulas: bool = True) -> ResultadoFerramenta:
    if de not in FORMATOS or para not in FORMATOS:
        raise ValidacaoDominio(f"formatos aceitos: {', '.join(FORMATOS)}")
    if len(delimitador) != 1:
        raise ValidacaoDominio("delimitador deve ter 1 caractere")
    linhas = _ler(texto, de, delimitador)
    saida, neutralizadas = _escrever(linhas, para, delimitador, neutralizar_formulas)
    avisos = []
    if neutralizadas:
        avisos.append(f"{neutralizadas} celula(s) iniciadas por =,+,-,@ receberam prefixo ' (protecao contra CSV injection)")
    truncado = len(saida) > MAX_SAIDA
    if truncado:
        avisos.append(f"saida cortada em {MAX_SAIDA} caracteres")
    r = montar("dados.converter", texto, saida[:MAX_SAIDA], {"registros": len(linhas), "de": de, "para": para,
                                                             "colunas": _colunas(linhas)}, truncado, avisos)
    return r
