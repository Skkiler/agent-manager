"""Mede a economia das ferramentas N0 em artefatos reais deste repositorio (tokens ESTIMADOS, ~4 car./token).

Uso: python scripts/medir_ferramentas.py [--commits 3]
Compara o material bruto (arquivo, diff, saida do pytest) com o resumo que o agente receberia. Nao mede qualidade:
a fidelidade e coberta por tests/test_ferramentas.py. Nada e gravado em disco.
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from forja.ferramentas.diff import resumir_diff  # noqa: E402
from forja.ferramentas.outline import outline_arquivo  # noqa: E402
from forja.ferramentas.testes import resumir_pytest  # noqa: E402
from forja.memoria.indexador import listar_arquivos  # noqa: E402


def _linha(nome: str, r) -> str:
    return f"{nome:<28} bruto={r.tokens_origem:>7} resumo={r.tokens_resumo:>6} reducao={r.reducao:6.1%}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commits", type=int, default=3, help="quantos commits recentes medir no resumo de diff")
    args = ap.parse_args()

    # 1. outline: todos os .py de forja/ com mais de 3.000 caracteres (arquivos pequenos nao valem a ferramenta)
    arquivos = [p for p in listar_arquivos(RAIZ / "forja", frozenset({".py"})) if p.stat().st_size > 3000]
    res = [outline_arquivo(RAIZ, p.relative_to(RAIZ).as_posix()) for p in arquivos]
    red = [r.reducao for r in res]
    print(f"[outline] {len(res)} arquivos | bruto total={sum(r.tokens_origem for r in res)} "
          f"resumo total={sum(r.tokens_resumo for r in res)} | reducao mediana={statistics.median(red):.1%} "
          f"min={min(red):.1%}")

    # 2. pytest com falhas reais (projeto temporario descartavel)
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        corpo = "".join(
            f"def test_f{i}():\n    dados = {{'a': {i}, 'b': [1, 2, 3]}}\n    assert dados['a'] == {i + 1}\n\n" for i in range(8)
        )
        (d / "test_x.py").write_text(corpo + "def test_ok():\n    assert True\n", encoding="utf-8")
        p = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-rfE", "test_x.py"], cwd=d,
                           capture_output=True, text=True, encoding="utf-8", check=False)
    print("[pytest]", _linha("8 falhas + 1 ok", resumir_pytest(p.stdout)))

    # 3. diff dos commits recentes
    for i in range(args.commits):
        p = subprocess.run(["git", "diff", f"HEAD~{i + 1}", f"HEAD~{i}"], cwd=RAIZ, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", check=False)
        if p.returncode == 0 and p.stdout:
            print("[diff]  ", _linha(f"HEAD~{i + 1}..HEAD~{i}", resumir_diff(p.stdout)))
    # 4. ferramentas de repositorio/banco (mesmo catalogo que o agente usa)
    from forja.adapters.sqlite.banco import migrar
    from forja.ferramentas.esquema import inspecionar_sqlite
    from forja.ferramentas.mapa import mapa_repositorio
    from forja.ferramentas.segredos import varrer

    print("[mapa]   ", _linha("repo.mapa (repositorio)", mapa_repositorio(RAIZ)))
    sec = varrer(RAIZ, "forja")
    print("[segredos]", _linha("segredos.varrer forja/", sec), f"| achados={len(sec.dados['achados'])}")
    with tempfile.TemporaryDirectory() as tmp:
        banco = Path(tmp) / "x.sqlite3"
        migrar(banco)
        print("[esquema]", _linha("sql.inspecionar (DDL real)", inspecionar_sqlite(Path(tmp), "x.sqlite3")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
