"""logs.agrupar_falhas: agrupa linhas de erro por assinatura (numeros, ids e caminhos normalizados)."""

from __future__ import annotations

import re
from collections import OrderedDict

from forja.ferramentas.contrato import ResultadoFerramenta, montar

MAX_GRUPOS = 10
MAX_EXEMPLO = 200

_ERRO = re.compile(
    r"\b(ERROR|CRITICAL|FATAL|Traceback|Exception|[A-Z][A-Za-z]+(?:Error|Exception)|falha|erro|timeout)\b", re.I
)
_NIVEL = re.compile(r"\b(CRITICAL|FATAL|ERROR|WARN(?:ING)?|INFO|DEBUG)\b")
_NORMALIZAR = (
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b"), "<ts>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<hex>"),
    (re.compile(r"\b[0-9a-f]{12,}\b", re.I), "<hash>"),
    (re.compile(r"(?:[A-Za-z]:)?[\\/](?:[\w.\-]+[\\/])+[\w.\-]+"), "<caminho>"),
    (re.compile(r"\b\d+(?:\.\d+)?\b"), "<n>"),
)


def assinatura(linha: str) -> str:
    s = linha.strip()
    for padrao, troca in _NORMALIZAR:
        s = padrao.sub(troca, s)
    return re.sub(r"\s+", " ", s)[:300]


def agrupar_falhas(texto: str, limite: int = MAX_GRUPOS) -> ResultadoFerramenta:
    grupos: OrderedDict[str, dict] = OrderedDict()
    niveis: dict[str, int] = {}
    total_linhas = 0
    for n, linha in enumerate(texto.splitlines(), 1):
        total_linhas += 1
        nivel = _NIVEL.search(linha)
        if nivel:
            niveis[nivel.group(1)] = niveis.get(nivel.group(1), 0) + 1
        if not _ERRO.search(linha):
            continue
        g = grupos.setdefault(assinatura(linha), {"contagem": 0, "primeira": n, "ultima": n, "exemplo": linha.strip()})
        g["contagem"] += 1
        g["ultima"] = n
    ordenados = sorted(grupos.items(), key=lambda kv: (-kv[1]["contagem"], kv[1]["primeira"]))
    topo = ordenados[:limite]
    ocorrencias = sum(g["contagem"] for _, g in ordenados)
    linhas = [f"{total_linhas} linhas, {ocorrencias} com erro em {len(ordenados)} padrao(oes) distinto(s)"]
    if niveis:
        linhas.append("niveis: " + ", ".join(f"{k}={v}" for k, v in sorted(niveis.items())))
    for i, (_, g) in enumerate(topo, 1):
        ex = g["exemplo"][:MAX_EXEMPLO]
        linhas.append(f"{i}. x{g['contagem']} (linhas {g['primeira']}-{g['ultima']}): {ex}")
    omitidos = len(ordenados) - len(topo)
    if omitidos > 0:
        linhas.append(f"(+{omitidos} padroes omitidos)")
    dados = {
        "total_linhas": total_linhas,
        "ocorrencias": ocorrencias,
        "niveis": niveis,
        "grupos": [{"assinatura": s, **g, "exemplo": g["exemplo"][:MAX_EXEMPLO]} for s, g in topo],
    }
    return montar("logs.agrupar_falhas", texto, "\n".join(linhas), dados, omitidos > 0)
