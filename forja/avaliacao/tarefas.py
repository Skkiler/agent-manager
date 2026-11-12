"""Benchmark de TAREFAS sinteticas (item 0.6): mede o orquestrador de ponta a ponta com criterio objetivo.

Cada tarefa traz um mini-projeto (arquivos), o pedido, o modo e criterios verificaveis pela Forja ("testes passam",
"arquivo: caminho") ou por texto esperado na resposta. Mede: estado, nivel do roteamento, chamadas ao modelo, tokens
estimados, tempo, resultado dos testes reais e criterios. Dados 100% sinteticos.

Uso: `python scripts/benchmark_tarefas.py` (agente FALSO: valida o arnes, sem custo) ou `--real` (Kiro real: consome creditos).
"""

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from forja.agentes.base import ControleExecucao

ARQUIVO = Path(__file__).with_name("tarefas.json")


@dataclass
class ResultadoTarefa:
    id: str
    nivel_esperado: str
    nivel: str = ""
    estado: str = ""
    sucesso: bool = False
    chamadas: int = 0
    tokens_entrada: int = 0
    segundos: float = 0.0
    testes_ok: bool | None = None
    criterios: str = ""
    motivo: str = ""
    eventos: list[str] = field(default_factory=list)
    modelos: list[str] = field(default_factory=list)  # parte=modelo/esforco aplicados na sessao, em ordem


def carregar(caminho: Path = ARQUIVO) -> list[dict[str, Any]]:
    return json.loads(caminho.read_text(encoding="utf-8"))


def _montar(t: dict[str, Any], base: Path) -> Path:
    proj = base / t["id"]
    for rel, conteudo in (t.get("arquivos") or {}).items():
        alvo = proj / rel
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(conteudo, encoding="utf-8")
    proj.mkdir(parents=True, exist_ok=True)
    return proj


def _aprovar_tudo(itens: list[dict[str, Any]]) -> dict[str, Any]:
    return {"aprovados": [i["id"] for i in itens], "adendo": "", "lembrar": True}


def rodar(provedor: Any, tarefas: list[dict[str, Any]], pasta: Path | None = None) -> list[ResultadoTarefa]:
    base = pasta or Path(tempfile.mkdtemp(prefix="forja-bench-"))
    saida = []
    for t in tarefas:
        proj = _montar(t, base)
        eventos: list[tuple[str, dict]] = []
        ctl = ControleExecucao(lambda c: None, lambda tp, d, ev=eventos: ev.append((tp, d)), _aprovar_tudo)
        tarefa = {"id": f"B-{t['id']}", "titulo": t["titulo"], "descricao": t.get("descricao", ""), "modo": t["modo"],
                  "criterios_aceite": t["criterios"], "especialidade": "geral",
                  "projeto_ctx": {"projeto": "bench", "pastas": [{"caminho": str(proj), "papel": "trabalho"}], "anexos": []}}
        t0 = time.monotonic()
        r = provedor.executar(tarefa, {}, ctl)
        res = ResultadoTarefa(t["id"], t["nivel"], segundos=round(time.monotonic() - t0, 1), estado=r.estado,
                              chamadas=r.consumo.chamadas_modelo, tokens_entrada=r.consumo.tokens_input or 0)
        rota = next((d for tp, d in eventos if tp == "kiro.rota"), {})
        res.nivel = rota.get("nivel", "")
        teste = next((d for tp, d in reversed(eventos) if tp == "kiro.testes_forja"), None)
        res.testes_ok = None if teste is None else bool(teste["ok"])
        crit = next((e.resumo for e in r.evidencias if e.tipo == "criterios_forja"), "")
        res.criterios = crit[:300]
        texto = "\n".join([a.conteudo for a in r.artefatos if a.nome.endswith(".md")] + [m.conteudo for m in r.mensagens])
        esperado = [s for s in t.get("resposta_contem", []) if s.casefold() not in texto.casefold()]
        falhos = "FALHOU" in crit or "sem prova" in crit
        res.sucesso = r.estado == "concluida" and not falhos and not esperado and res.testes_ok is not False
        res.motivo = ("; ".join(r.pendencias[:3]) if r.estado != "concluida" else
                      f"faltou na resposta: {esperado}" if esperado else "criterio nao atendido" if falhos else "")[:300]
        res.eventos = sorted({tp for tp, _ in eventos})[:30]
        res.modelos = [f"{d.get('parte')}={(d.get('aplicados') or {}).get('modelo', '-')}/{(d.get('aplicados') or {}).get('esforco', '-')}"
                       for tp, d in eventos if tp == "kiro.configuracao"]
        saida.append(res)
    return saida


def resumo(resultados: list[ResultadoTarefa]) -> dict[str, Any]:
    n = len(resultados) or 1
    por_nivel: dict[str, dict[str, Any]] = {}
    for r in resultados:
        g = por_nivel.setdefault(r.nivel_esperado, {"tarefas": 0, "sucesso": 0, "chamadas": 0, "tokens": 0, "segundos": 0.0})
        g["tarefas"] += 1
        g["sucesso"] += int(r.sucesso)
        g["chamadas"] += r.chamadas
        g["tokens"] += r.tokens_entrada
        g["segundos"] += r.segundos
    return {"tarefas": len(resultados), "taxa_sucesso": round(sum(r.sucesso for r in resultados) / n, 3),
            "roteamento_correto": round(sum(r.nivel == r.nivel_esperado for r in resultados) / n, 3),
            "chamadas_por_tarefa": round(sum(r.chamadas for r in resultados) / n, 2),
            "tokens_entrada_por_tarefa": round(sum(r.tokens_entrada for r in resultados) / n),
            "por_nivel": por_nivel, "resultados": [asdict(r) for r in resultados]}
