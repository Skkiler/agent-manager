"""Roteamento que aprende com o uso (sem LLM): taxa de sucesso por nivel/parte/modelo, media movel exponencial.

Ao terminar cada execucao REAL (com evento `kiro.rota`), registra sucesso (concluida) ou falha (falhou, expirou, ou
bloqueou porque os testes/criterios da Forja nao passaram ou um orcamento estourou). Bloqueios por decisao do usuario e
cancelamentos nao contam (nao dizem nada sobre a rota).

Ajuste: se um nivel tem pelo menos MIN_EXECUCOES e taxa abaixo de LIMIAR, as proximas tarefas desse nivel sobem um degrau
(mais planejamento/esforco). Nunca rebaixa sozinho: errar para o lado caro e seguro, errar para o barato repete falhas.
"""

from __future__ import annotations

import logging
from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.dominio.tempo import Relogio, RelogioSistema, iso
from forja.orquestracao.roteamento import Rota, promover

log = logging.getLogger("forja.rotas")
ALFA = 0.3  # peso da execucao mais recente
MIN_EXECUCOES = 5
LIMIAR = 0.6
_FALHA_PENDENCIA = ("testes_falhando", "criterios_nao_atendidos", "orcamento_ferramentas_excedido", "laco_detectado", "regressao")


def desfecho(ex: dict[str, Any]) -> bool | None:
    """True = sucesso, False = falha da rota, None = nao conta."""
    estado = ex.get("estado")
    if estado == "concluida":
        return True
    if estado in ("falhou", "expirada"):
        return False
    if estado == "pausada":
        pend = " ".join((ex.get("resultado") or {}).get("pendencias") or [])
        return False if any(p in pend for p in _FALHA_PENDENCIA) else None
    return None


class AprendizadoRotas:
    def __init__(self, repo: RepositorioSqlite, relogio: Relogio | None = None) -> None:
        self.repo = repo
        self.relogio = relogio or RelogioSistema()
        self.ativo = True

    def ao_finalizar(self, execucao_id: str, _res: Any = None) -> None:
        try:
            with self.repo.leitura() as t:
                ex = t.obter(T.Execucao, execucao_id)
                eventos = t.eventos_da_execucao(execucao_id)
            if ex is None:
                return
            rota = next((e["payload"] for e in eventos if e["tipo"] == "kiro.rota"), None)
            ok = desfecho(ex)
            if not rota or ok is None:
                return
            modelos = [((e["payload"] or {}).get("aplicados") or {}).get("modelo") for e in eventos if e["tipo"] == "kiro.configuracao"]
            modelo = next((m for m in reversed(modelos) if m), "padrao")
            self.registrar(str(rota.get("nivel")), str(rota.get("parte")), str(modelo), ok)
        except Exception as e:  # noqa: BLE001 - aprendizado e otimizacao; nunca altera a execucao
            log.warning("falha ao registrar estatistica de rota: %s", type(e).__name__)

    def registrar(self, nivel: str, parte: str, modelo: str, ok: bool) -> dict[str, Any]:
        chave = f"{nivel}|{parte}|{modelo}"[:200]
        agora = iso(self.relogio.agora())
        with self.repo.escrita() as t:
            atual = t.s.get(T.EstatisticaRota, chave)
            if atual is None:
                t.inserir(T.EstatisticaRota, chave=chave, nivel=nivel[:16], parte=parte[:32], modelo=modelo[:120], execucoes=1,
                          sucessos=int(ok), taxa=1.0 if ok else 0.0, atualizado_em=agora)
            else:
                atual.execucoes += 1
                atual.sucessos += int(ok)
                atual.taxa = round((1 - ALFA) * atual.taxa + ALFA * (1.0 if ok else 0.0), 4)
                atual.atualizado_em = agora
                t.s.flush()
            linha = t.obter(T.EstatisticaRota, chave)
            return {"chave": chave, "execucoes": linha["execucoes"], "taxa": linha["taxa"]}

    def por_nivel(self) -> dict[str, dict[str, float]]:
        saida: dict[str, dict[str, float]] = {}
        with self.repo.leitura() as t:
            for x in t.listar(T.EstatisticaRota, ordem=T.EstatisticaRota.chave, limite=10_000):
                s = saida.setdefault(x["nivel"], {"execucoes": 0, "peso": 0.0})
                s["execucoes"] += x["execucoes"]
                s["peso"] += x["taxa"] * x["execucoes"]
        return {n: {"execucoes": v["execucoes"], "taxa": round(v["peso"] / max(v["execucoes"], 1), 3)} for n, v in saida.items()}

    def ajustar(self, rota: Rota, tarefa: dict[str, Any]) -> Rota:
        """Promove a rota quando o nivel dela vem falhando. Nivel forcado pelo usuario na tarefa nunca muda."""
        if not self.ativo or ((tarefa.get("politicas") or {}).get("complexidade") or "").strip():
            return rota
        try:
            s = self.por_nivel().get(rota.nivel)
        except Exception:  # noqa: BLE001
            return rota
        if not s or s["execucoes"] < MIN_EXECUCOES or s["taxa"] >= LIMIAR:
            return rota
        escreve = tarefa.get("modo") in ("alteracao_codigo", "verificacao")
        return promover(rota, escreve, f"aprendido: nivel '{rota.nivel}' com {int(s['taxa'] * 100)}% de sucesso em {s['execucoes']} execucoes")

    def resumo(self) -> list[dict[str, Any]]:
        with self.repo.leitura() as t:
            return [{k: x[k] for k in ("nivel", "parte", "modelo", "execucoes", "sucessos", "taxa", "atualizado_em")}
                    for x in t.listar(T.EstatisticaRota, ordem=T.EstatisticaRota.chave, limite=10_000)]
