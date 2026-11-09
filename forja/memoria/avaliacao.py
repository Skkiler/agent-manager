"""Avaliacao de recuperacao: recall@k, MRR e nDCG@k. Puro. Serve para provar ganho ANTES de adotar uma tecnica."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Caso:
    consulta: str
    relevantes: frozenset[str]
    categoria: str = "geral"


def metricas_do_caso(ranking: list[str], relevantes: frozenset[str], k: int) -> dict[str, float]:
    topo = ranking[:k]
    achados = [i for i in topo if i in relevantes]
    recall = len(set(achados)) / len(relevantes) if relevantes else 0.0
    rr = next((1.0 / pos for pos, i in enumerate(ranking, start=1) if i in relevantes), 0.0)
    dcg = sum(1.0 / math.log2(pos + 1) for pos, i in enumerate(topo, start=1) if i in relevantes)
    ideal = sum(1.0 / math.log2(pos + 1) for pos in range(1, min(len(relevantes), k) + 1))
    return {"recall": recall, "rr": rr, "ndcg": dcg / ideal if ideal else 0.0}


def avaliar(buscar: Callable[[str], list[str]], casos: list[Caso], k: int = 5) -> dict[str, object]:
    """`buscar(consulta)` devolve chaves em ordem de relevancia. Retorna medias globais e por categoria."""
    por_cat: dict[str, list[dict[str, float]]] = defaultdict(list)
    todos = []
    for c in casos:
        m = metricas_do_caso(buscar(c.consulta), c.relevantes, k)
        por_cat[c.categoria].append(m)
        todos.append(m)

    def media(ms: list[dict[str, float]]) -> dict[str, float]:
        n = len(ms) or 1
        return {f"recall@{k}": round(sum(m["recall"] for m in ms) / n, 3),
                "mrr": round(sum(m["rr"] for m in ms) / n, 3),
                f"ndcg@{k}": round(sum(m["ndcg"] for m in ms) / n, 3), "casos": len(ms)}

    return {"global": media(todos), "por_categoria": {c: media(ms) for c, ms in sorted(por_cat.items())}}


def carregar_benchmark(caminho: Path) -> tuple[list[dict], list[Caso]]:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    casos = [Caso(c["q"], frozenset(c["relevantes"]), c.get("categoria", "geral")) for c in dados["consultas"]]
    return dados["memorias"] + dados.get("ruido", []), casos


def comparar(servico, principal, memorias: list[dict], casos: list[Caso], k: int = 5,
             namespace: str = "publico/benchmark") -> dict[str, object]:
    """Carrega o corpus no `servico` e compara baseline (expandir=False) x busca nova (expandir=True)."""
    from forja.memoria.contratos import MemoriaIn

    chave_de: dict[str, str] = {}
    for m in memorias:
        criada = servico.criar(principal, MemoriaIn(
            tipo=m["tipo"], titulo=m["titulo"], resumo=m["resumo"], conteudo=m["conteudo"], tags=m["tags"],
            namespace=namespace))
        chave_de[criada["id"]] = m["chave"]

    def ranking(expandir: bool) -> Callable[[str], list[str]]:
        def f(q: str) -> list[str]:
            try:
                r = servico.buscar(principal, q, [namespace], fontes=("memoria",), limite=10, expandir=expandir)
            except Exception:  # noqa: BLE001 - consulta sem termos conta como zero acertos
                return []
            return [chave_de[i["id"]] for i in r["resultados"] if i["id"] in chave_de]
        return f

    return {"baseline": avaliar(ranking(False), casos, k), "nova": avaliar(ranking(True), casos, k)}
