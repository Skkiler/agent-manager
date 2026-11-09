"""Alimenta o segundo cerebro a partir de um diretorio local (incremental, por SHA-256) e, opcionalmente, o observa.

Uso:
  python scripts/memoria_ingerir.py --raiz <pasta> --namespace publico/meu-repo --repositorio meu-repo
         [--db data/forja.sqlite3] [--extensoes .py .md] [--commit <sha>]
         [--watch --intervalo 30] [--consultar "classe X" "erro Y"] [--mostrar-trechos]

Seguranca:
  * Roda LOCAL; nada sai da maquina. O banco fica em data/ (ignorado pelo Git).
  * Por padrao imprime SOMENTE agregados (contagens e tempos). Caminhos/trechos so com --consultar / --mostrar-trechos.
  * Segredos (.env, chaves, tokens), binarios, symlinks e caches sao ignorados; PII/segredos no texto sao redigidos antes de indexar.
  * Para dados de empresa use um namespace 'empresa/<id>' e um banco proprio via --db.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forja.adapters.sqlite.banco import criar_engines, migrar  # noqa: E402
from forja.adapters.sqlite.repositorio import RepositorioSqlite  # noqa: E402
from forja.memoria.contratos import IngerirIn  # noqa: E402
from forja.memoria.modelo import Principal, validar_namespace  # noqa: E402
from forja.orquestracao.memoria_servico import ServicoMemoria  # noqa: E402


def ingerir_uma_vez(s: ServicoMemoria, p: Principal, args: argparse.Namespace) -> dict:
    t0 = time.perf_counter()
    r = s.ingerir_diretorio(
        p,
        IngerirIn(
            namespace=args.namespace,
            raiz=args.raiz,
            repositorio=args.repositorio,
            commit_sha=args.commit,
            extensoes=args.extensoes,
        ),
    )
    r["segundos"] = round(time.perf_counter() - t0, 2)
    return r


def resumo(r: dict) -> str:
    base = {k: v for k, v in r.items() if k != "memorias_marcadas"}
    return f"{base} | memorias_marcadas_para_revalidacao={len(r.get('memorias_marcadas', []))}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raiz", required=True)
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--repositorio", required=True)
    ap.add_argument("--db", default="data/forja.sqlite3")
    ap.add_argument("--extensoes", nargs="*", default=[])
    ap.add_argument("--commit", default="")
    ap.add_argument("--watch", action="store_true", help="reindexa a cada --intervalo segundos (so o que mudou)")
    ap.add_argument("--intervalo", type=int, default=30)
    ap.add_argument("--consultar", nargs="*", default=[])
    ap.add_argument("--mostrar-trechos", action="store_true")
    args = ap.parse_args()

    ns = validar_namespace(args.namespace)
    raiz = Path(args.raiz).resolve()
    if not raiz.is_dir():
        print(f"[erro] raiz inexistente: {raiz.name}")
        return 2
    args.raiz = str(raiz)
    db = Path(args.db)
    migrar(db)
    w, r = criar_engines(db)
    repo = RepositorioSqlite(w, r)
    try:
        s = ServicoMemoria(repo, raizes_ingestao=[raiz])
        p = Principal("cli-local", frozenset({ns}))
        print("[ingestao]", resumo(ingerir_uma_vez(s, p, args)))
        print("[estatisticas]", s.estatisticas(p))
        for q in args.consultar:
            t0 = time.perf_counter()
            res = s.buscar(p, q, [ns], limite=3)
            ms = (time.perf_counter() - t0) * 1000
            topo = [(x.get("caminho") or x.get("titulo"), x.get("linhas")) for x in res["resultados"]]
            print(
                f"[busca] {len(q)} chars | {ms:.1f} ms | {len(res['resultados'])} resultado(s) | cobertura media="
                f"{sum(x.get('cobertura', 1.0) for x in res['resultados']) / max(len(res['resultados']), 1):.2f}"
            )
            if args.mostrar_trechos:
                for (nome, linhas), x in zip(topo, res["resultados"], strict=False):
                    print(f"    {nome} {linhas or ''}\n      {x['trecho'][:160]!r}")
        while args.watch:
            time.sleep(args.intervalo)
            r2 = ingerir_uma_vez(s, p, args)
            if r2["novos"] or r2["alterados"] or r2["removidos"]:
                print("[watch]", resumo(r2))
    except KeyboardInterrupt:
        print("[watch] encerrado")
    finally:
        repo.fechar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
