"""Painel de custo: chamadas de modelo, tokens e creditos por dia, parte do sistema, modelo e tarefa.

CREDITOS MEDIDOS (preferidos): o kiro-cli 3.1.0 envia, a cada turno, o consumo real da sessao (`session_usage`); o provedor soma
por execucao em `consumo.creditos`. Execucoes sem essa medida (versoes antigas, Codex, mock) ficam so na ESTIMATIVA, que usa o
que a Forja mede de verdade:
- turnos de modelo de cada execucao (chamadas_modelo) e o modelo aplicado em cada turno (eventos kiro.configuracao);
- o multiplicador de creditos de cada modelo listado pela sua conta (`kiro-cli chat --list-models`; 1,00x se desconhecido);
- tokens estimados (~4 caracteres por token) do que a Forja enviou e recebeu.
creditos_estimados = soma(turnos x multiplicador do modelo). Execucoes simuladas (mock) custam zero. Tudo rotulado como estimativa.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.dominio.tempo import Relogio, RelogioSistema, iso

NOTA = ("Créditos medidos: o valor que o próprio Kiro informa a cada turno (preferido). Estimativa (quando não há medida): turnos de "
        "modelo x multiplicador de créditos do modelo (lista da sua conta Kiro; 1,00x quando desconhecido). Tokens são estimados pela "
        "Forja (~4 caracteres/token). O valor faturado aparece no painel da sua conta.")


class CustosServico:
    def __init__(self, repo: RepositorioSqlite, catalogo: Any | None = None, relogio: Relogio | None = None) -> None:
        self.repo = repo
        self.catalogo = catalogo
        self.relogio = relogio or RelogioSistema()

    def _multiplicadores(self) -> dict[str, float]:
        try:
            return {m["id"]: float(m["custo"]) for m in (self.catalogo.listar().get("modelos") or [])} if self.catalogo else {}
        except Exception:  # noqa: BLE001 - sem catalogo, todo modelo vale 1,00x (rotulado)
            return {}

    def painel(self, dias: int = 30) -> dict[str, Any]:
        dias = max(1, min(int(dias), 365))
        desde = iso(self.relogio.agora() - timedelta(days=dias))
        with self.repo.leitura() as t:
            execs = [SimpleNamespace(id=e.id, tarefa_id=e.tarefa_id, criado_em=e.criado_em, resultado=e.resultado)
                     for e in t.s.query(T.Execucao).filter(T.Execucao.criado_em >= desde).order_by(T.Execucao.criado_em).limit(5000)]
            ids = [e.id for e in execs]
            configs: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for i in range(0, len(ids), 500):
                for ev in t.s.query(T.Evento).filter(T.Evento.tipo == "kiro.configuracao", T.Evento.execucao_id.in_(ids[i:i + 500])).order_by(T.Evento.seq):
                    configs[ev.execucao_id].append(ev.payload or {})
            titulos = {x.id: x.titulo for x in t.s.query(T.Tarefa.id, T.Tarefa.titulo).filter(T.Tarefa.id.in_({e.tarefa_id for e in execs}))} if execs else {}
        mult = self._multiplicadores()
        total = {"execucoes": 0, "simuladas": 0, "chamadas": 0, "tokens_entrada": 0, "tokens_saida": 0, "creditos_estimados": 0.0,
                 "creditos_medidos": 0.0, "execucoes_medidas": 0}
        por_dia: dict[str, dict[str, float]] = defaultdict(lambda: {"execucoes": 0, "chamadas": 0, "creditos_estimados": 0.0,
                                                                    "creditos_medidos": 0.0})
        por_parte: dict[str, dict[str, float]] = defaultdict(lambda: {"turnos": 0, "creditos_estimados": 0.0, "creditos_medidos": 0.0})
        por_modelo: dict[str, dict[str, float]] = defaultdict(lambda: {"turnos": 0, "multiplicador": 1.0, "creditos_estimados": 0.0,
                                                                       "creditos_medidos": 0.0})
        por_tarefa: dict[str, float] = defaultdict(float)  # melhor valor por tarefa: medido quando houver, senao estimado
        for e in execs:
            res = e.resultado or {}
            consumo = res.get("consumo") or {}
            mock = bool(res.get("mock"))
            chamadas = int(res.get("chamadas_acumuladas") or consumo.get("chamadas_modelo") or 0)
            medido = consumo.get("creditos")
            medido = float(medido) if isinstance(medido, (int, float)) and not mock else None
            total["execucoes"] += 1
            total["simuladas"] += int(mock)
            total["chamadas"] += chamadas
            total["tokens_entrada"] += int(consumo.get("tokens_input") or 0)
            total["tokens_saida"] += int(consumo.get("tokens_output") or 0)
            dia = (e.criado_em or "")[:10]
            por_dia[dia]["execucoes"] += 1
            por_dia[dia]["chamadas"] += chamadas
            if medido is not None:
                total["creditos_medidos"] += medido
                total["execucoes_medidas"] += 1
                por_dia[dia]["creditos_medidos"] += medido
            if mock or chamadas == 0:
                if medido is not None:
                    por_tarefa[e.tarefa_id] += medido
                continue
            turnos = self._turnos(configs.get(e.id, []), chamadas)
            pesos = [mult.get(modelo, 1.0) for modelo, _ in turnos]
            soma_pesos = sum(pesos) or 1.0
            for (modelo, parte), m in zip(turnos, pesos, strict=True):
                fatia = medido * m / soma_pesos if medido is not None else 0.0  # o medido e repartido pelo peso de cada turno
                por_modelo[modelo]["turnos"] += 1
                por_modelo[modelo]["multiplicador"] = m
                por_modelo[modelo]["creditos_estimados"] += m
                por_modelo[modelo]["creditos_medidos"] += fatia
                por_parte[parte]["turnos"] += 1
                por_parte[parte]["creditos_estimados"] += m
                por_parte[parte]["creditos_medidos"] += fatia
                por_dia[dia]["creditos_estimados"] += m
                total["creditos_estimados"] += m
            por_tarefa[e.tarefa_id] += medido if medido is not None else soma_pesos

        def r(kk: str, vv: float) -> float:
            return round(vv, 4 if "medidos" in kk else 2)

        def arred(d: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
            return {k: {kk: (r(kk, vv) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in sorted(d.items())}

        mais = sorted(por_tarefa.items(), key=lambda kv: -kv[1])[:5]
        medidas = total["execucoes_medidas"]
        reais = total["execucoes"] - total["simuladas"]
        return {"dias": dias, "desde": desde, "estimativa": not (reais > 0 and medidas == reais), "nota": NOTA, "catalogo_disponivel": bool(mult),
                "cobertura_medida": round(medidas / reais, 2) if reais else 0.0,
                "alertas": self._desvios(por_dia, dias),
                "total": {**total, "creditos_estimados": round(total["creditos_estimados"], 2),
                          "creditos_medidos": round(total["creditos_medidos"], 4)},
                "por_dia": [{"dia": k, **v} for k, v in arred(por_dia).items()],
                "por_parte": arred(por_parte), "por_modelo": arred(por_modelo),
                "mais_caras": [{"tarefa_id": k, "titulo": titulos.get(k, k), "creditos_estimados": round(v, 4)} for k, v in mais]}

    def gasto_hoje(self) -> float:
        """Creditos de hoje (UTC, como o painel): medido quando o agente informa; senao 1,00x por chamada de modelo. Simuladas nao contam."""
        hoje = iso(self.relogio.agora())[:10]
        total = 0.0
        with self.repo.leitura() as t:
            for e in t.s.query(T.Execucao).filter(T.Execucao.criado_em >= hoje).limit(5000):
                res = e.resultado or {}
                if res.get("mock"):
                    continue
                consumo = res.get("consumo") or {}
                medido = consumo.get("creditos")
                total += float(medido) if isinstance(medido, (int, float)) else float(res.get("chamadas_acumuladas") or consumo.get("chamadas_modelo") or 0)
        return round(total, 4)

    def teto_atingido(self, teto: float) -> str | None:
        """Mensagem quando o teto diario foi atingido (None = pode executar)."""
        if not teto or teto <= 0:
            return None
        gasto = self.gasto_hoje()
        if gasto < teto:
            return None
        return (f"Teto diário de créditos atingido ({gasto:.2f} de {teto:.0f}). A Forja não inicia novas execuções hoje; "
                "aumente o teto em Configurações > Consumo ou aguarde até amanhã.")

    def _desvios(self, por_dia: dict[str, dict[str, float]], dias: int) -> list[str]:
        """Alerta de desvio: os ultimos 7 dias gastaram mais que o DOBRO da media semanal do resto do periodo (min. 14 dias)."""
        if dias < 14:
            return []
        corte = iso(self.relogio.agora() - timedelta(days=7))[:10]
        recente = sum(v["creditos_estimados"] for d, v in por_dia.items() if d >= corte)
        antes = sum(v["creditos_estimados"] for d, v in por_dia.items() if d < corte)
        media_semana = antes / max((dias - 7) / 7, 1)
        if recente >= 5 and media_semana > 0 and recente > 2 * media_semana:
            return [f"Os últimos 7 dias gastaram ~{recente:.1f} créditos estimados, mais que o dobro da média semanal anterior "
                    f"(~{media_semana:.1f}). Veja as tarefas mais caras."]
        return []

    @staticmethod
    def _turnos(configs: list[dict[str, Any]], chamadas: int) -> list[tuple[str, str]]:
        """Distribui as chamadas pelos modelos aplicados: um turno por configuracao, o resto no ultimo modelo aplicado."""
        aplicados = [(((c.get("aplicados") or {}).get("modelo")) or "padrao", str(c.get("parte") or "execucao")) for c in configs]
        if not aplicados:
            return [("padrao", "execucao")] * chamadas
        turnos = aplicados[:chamadas]
        turnos += [aplicados[-1]] * max(0, chamadas - len(turnos))
        return turnos
