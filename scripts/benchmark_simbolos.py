"""Mede a busca de DEFINICOES sobre um indice real, sem rotulagem manual e sem expor conteudo.

Sorteia simbolos (classes/funcoes/metodos) do proprio indice, busca pelo nome e verifica se o arquivo que o DEFINE
aparece no top-k. Nomes definidos em varios arquivos sao ambiguos e reportados a parte (nao ha 'resposta unica').
Imprime SOMENTE agregados (taxas e latencias): nenhum caminho, nome ou trecho.

Uso: python scripts/benchmark_simbolos.py --db data/x.sqlite3 --namespace empresa/local [--amostra 300] [--k 3]
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from forja.adapters.sqlite.banco import criar_engines  # noqa: E402
from forja.adapters.sqlite.repositorio import RepositorioSqlite  # noqa: E402
from forja.memoria.modelo import Principal, validar_namespace  # noqa: E402
from forja.orquestracao.memoria_servico import ServicoMemoria  # noqa: E402


def percentil(valores: list[float], p: float) -> float:
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, int(len(ordenados) * p))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--amostra", type=int, default=300)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--semente", type=int, default=7)
    args = ap.parse_args()
    ns = validar_namespace(args.namespace)
    w, r = criar_engines(Path(args.db))
    repo = RepositorioSqlite(w, r)
    try:
        s = ServicoMemoria(repo)
        p = Principal("bench", frozenset({ns}))
        with repo.leitura() as t:
            linhas = t.s.execute(
                text(
                    "SELECT s.nome, a.caminho FROM simbolo s JOIN arquivo_indexado a ON a.id = s.arquivo_id "
                    "WHERE a.estado = 'ativo' AND s.tipo IN ('classe', 'funcao') AND length(s.nome) >= 6 "
                    "AND (a.namespace = :n OR substr(a.namespace, 1, length(:n) + 1) = :n || '/')"
                ),
                {"n": ns},
            ).all()
        onde: dict[str, set[str]] = defaultdict(set)
        for nome, caminho in linhas:
            onde[nome].add(caminho)
        unicos = [(n, next(iter(c))) for n, c in onde.items() if len(c) == 1]
        ambiguos = [(n, c) for n, c in onde.items() if len(c) > 1]
        print(f"[indice] simbolos distintos={len(onde)} | com definicao unica={len(unicos)} | ambiguos={len(ambiguos)}")
        if not unicos:
            print("[aviso] nada para medir")
            return 1
        random.Random(args.semente).shuffle(unicos)
        amostra = unicos[: args.amostra]
        acertos, ms = 0, []
        for nome, caminho in amostra:
            t0 = time.perf_counter()
            res = s.buscar(p, nome, [ns], limite=args.k, fontes=("codigo",))
            ms.append((time.perf_counter() - t0) * 1000)
            if any(x["caminho"] == caminho for x in res["resultados"][: args.k]):
                acertos += 1
        print(
            f"[definicao unica] amostra={len(amostra)} | acerto@{args.k}={acertos / len(amostra):.3f} ({acertos}/{len(amostra)})"
        )
        print(f"[latencia ms] mediana={statistics.median(ms):.1f} p95={percentil(ms, 0.95):.1f} max={max(ms):.1f}")
        if ambiguos:
            random.Random(args.semente).shuffle(ambiguos)
            amb = ambiguos[: min(100, len(ambiguos))]
            cobertos = 0
            for nome, caminhos in amb:
                res = s.buscar(p, nome, [ns], limite=args.k, fontes=("codigo",))
                cobertos += 1 if any(x["caminho"] in caminhos for x in res["resultados"][: args.k]) else 0
            print(
                f"[nomes ambiguos] amostra={len(amb)} | ao menos uma definicao no top-{args.k}={cobertos / len(amb):.3f}"
            )
    finally:
        repo.fechar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
