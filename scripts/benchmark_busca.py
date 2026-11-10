"""Benchmark reprodutivel da busca da memoria: baseline lexical x busca com radicais/sinonimos.

Uso: python scripts/benchmark_busca.py [--k 5] [--json]
Dados: knowledge/modelos_publicos/benchmark_busca.json (sintetico e publico). Usa banco temporario; nao toca em data/.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forja.adapters.sqlite.banco import criar_engines, migrar  # noqa: E402
from forja.adapters.sqlite.repositorio import RepositorioSqlite  # noqa: E402
from forja.memoria.avaliacao import carregar_benchmark, comparar  # noqa: E402
from forja.memoria.modelo import Principal  # noqa: E402
from forja.orquestracao.memoria_servico import ServicoMemoria  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]


def executar(k: int = 5, glossario: bool = False) -> dict:
    db = Path(tempfile.mkdtemp(prefix="forja-bench-")) / "b.sqlite3"
    migrar(db)
    w, r = criar_engines(db)
    repo = RepositorioSqlite(w, r)
    try:
        from forja.memoria.linguagem import caminho_sinonimos

        servico = ServicoMemoria(repo, sinonimos=caminho_sinonimos() if glossario else None)
        memorias, casos = carregar_benchmark(RAIZ / "knowledge" / "modelos_publicos" / "benchmark_busca.json")
        return comparar(servico, Principal("bench", frozenset({"publico"})), memorias, casos, k)
    finally:
        repo.fechar()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--glossario", action="store_true", help="inclui a extensao opcional de sinonimos")
    args = ap.parse_args()
    res = executar(args.k, args.glossario)
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        sys.exit(0)
    k = args.k
    print(f"{'':10}{'baseline':>22}{'nova':>22}   (recall@{k} / MRR / nDCG@{k})")
    for cat in ["GLOBAL", *res["baseline"]["por_categoria"]]:
        b = (
            res["baseline"]["global" if cat == "GLOBAL" else "por_categoria"][cat]
            if cat != "GLOBAL"
            else res["baseline"]["global"]
        )
        n = res["nova"]["global"] if cat == "GLOBAL" else res["nova"]["por_categoria"][cat]
        fmt = lambda m: f"{m[f'recall@{k}']:.2f}/{m['mrr']:.2f}/{m[f'ndcg@{k}']:.2f}"  # noqa: E731
        print(f"{cat:10}{fmt(b):>22}{fmt(n):>22}   n={b['casos']}")
