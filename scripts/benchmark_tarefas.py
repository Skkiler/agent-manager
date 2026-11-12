"""Benchmark de tarefas sinteticas de ponta a ponta (item 0.6). Ver forja/avaliacao/tarefas.py.

Uso:
  python scripts/benchmark_tarefas.py                 # agente FALSO: valida o arnes (roteamento, grafo, verificacao), sem custo
  python scripts/benchmark_tarefas.py --real [--ids n1-media-vazia,s1-explicar-media]   # Kiro real: CONSOME creditos
  python scripts/benchmark_tarefas.py --json saida.json
O modo falso NAO mede a qualidade do agente (o agente falso nao programa); so prova que a medicao funciona.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp, montar_comando, resolver_cli  # noqa: E402
from forja.adapters.sqlite.banco import criar_engines, migrar  # noqa: E402
from forja.adapters.sqlite.repositorio import RepositorioSqlite  # noqa: E402
from forja.agentes.estilo import PerfilTrabalho  # noqa: E402
from forja.avaliacao.tarefas import carregar, resumo, rodar  # noqa: E402
from forja.orquestracao.configuracao_servico import ConfiguracaoServico  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true", help="usa o kiro-cli (consome creditos)")
    ap.add_argument("--ids", default="", help="subconjunto (ids separados por virgula)")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    tarefas = carregar()
    if a.ids:
        quero = {x.strip() for x in a.ids.split(",")}
        tarefas = [t for t in tarefas if t["id"] in quero]
    tmp = Path(tempfile.mkdtemp(prefix="forja-bench-"))
    db = tmp / "b.sqlite3"
    migrar(db)
    cfg = ConfiguracaoServico(RepositorioSqlite(*criar_engines(db)))  # padroes da Forja (hierarquia de modelos)
    if a.real:
        cli = resolver_cli()
        if not cli:
            print("kiro-cli nao encontrado")
            return 2
        comando = montar_comando(cli)
    else:
        comando = [sys.executable, str(Path(__file__).resolve().parents[1] / "tests" / "fakes" / "fake_acp_agent.py"), "planeja_x"]
    prov = ProvedorKiroAcp(comando, tmp / "ws", timeout_prompt=600, modelo_de=cfg.modelo_para, esforco_de=cfg.esforco_para,
                           perfil_de=lambda: PerfilTrabalho(nivel="total", testes_timeout_s=120))
    prov.alternativas_de = cfg.alternativas_para
    r = resumo(rodar(prov, tarefas, tmp / "projetos"))
    print(f"{'REAL' if a.real else 'SIMULADO (agente falso)'}: {r['tarefas']} tarefas | sucesso {r['taxa_sucesso']:.0%} | "
          f"roteamento correto {r['roteamento_correto']:.0%} | {r['chamadas_por_tarefa']} chamadas/tarefa | ~{r['tokens_entrada_por_tarefa']} tokens entrada/tarefa")
    for x in r["resultados"]:
        print(f"  {x['id']:<20} esperado={x['nivel_esperado']:<8} roteado={x['nivel']:<8} {x['estado']:<10} ok={x['sucesso']!s:<5} "
              f"chamadas={x['chamadas']} {x['segundos']}s testes={x['testes_ok']} {' > '.join(x['modelos'])} {x['motivo'][:80]}")
    if a.json:
        Path(a.json).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
