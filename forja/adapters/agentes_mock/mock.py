"""AGENTE MOCK (SIMULADO). Nao chama Kiro nem modelo algum; serve para validar o nucleo.

Cenarios em tarefa.entrada.mock_cenario: sucesso (padrao) | falha | bloqueio.
Parametros: mock_passos (1..50, padrao 3), mock_passo_ms (0..1000, padrao 0).
Toda evidencia produzida e marcada simulada=True: NAO comprova funcionalidade real.
"""

from __future__ import annotations

import json
import time
from typing import Any

from forja.agentes.base import ControleExecucao
from forja.dominio.contratos import ArtefatoSaida, ConsumoMedicao, EvidenciaSaida, ResultadoAgente


def _limitar(v: Any, minimo: int, maximo: int, padrao: int) -> int:
    try:
        return max(minimo, min(maximo, int(v)))
    except (TypeError, ValueError):
        return padrao


class AgenteMock:
    id = "mock.deterministico"
    mock = True

    def executar(self, tarefa: dict[str, Any], checkpoint: dict[str, Any], ctl: ControleExecucao) -> ResultadoAgente:
        t0 = time.monotonic()
        entrada = tarefa.get("entrada") or {}
        cenario = str(entrada.get("mock_cenario", "sucesso"))
        passos = _limitar(entrada.get("mock_passos"), 1, 50, 3)
        passo_ms = _limitar(entrada.get("mock_passo_ms"), 0, 1000, 0)
        inicio = int(checkpoint.get("passo", 0))

        for i in range(inicio, passos):
            if ctl.cancelado():
                return self._res("cancelada", "Cancelado durante a simulacao.", t0)
            if ctl.pausado():
                return self._res("pausada", f"Pausado no passo {i}.", t0)
            ctl.dormir(passo_ms / 1000)
            if ctl.cancelado():
                return self._res("cancelada", "Cancelado durante a simulacao.", t0)
            if ctl.pausado():
                return self._res("pausada", f"Pausado no passo {i}.", t0)
            ctl.registrar_checkpoint({"passo": i + 1, "total": passos})
            ctl.evento("agente.passo", {"passo": i + 1, "total": passos, "mock": True})

        if cenario == "falha":
            return self._res("falhou", "Falha simulada solicitada pelo cenario.", t0)
        if cenario == "bloqueio":
            r = self._res("bloqueada", "Bloqueio simulado solicitado pelo cenario.", t0)
            r.pendencias.append("Intervencao manual simulada necessaria.")
            return r

        relatorio = json.dumps(
            {"simulado": True, "tarefa": tarefa["id"], "passos": passos, "criterios": tarefa["criterios_aceite"]},
            ensure_ascii=False,
            sort_keys=True,
        )
        r = self._res("concluida", "Execucao simulada concluida (nenhum trabalho real foi feito).", t0)
        r.artefatos.append(ArtefatoSaida(nome="relatorio.json", tipo="json", conteudo=relatorio))
        r.evidencias.append(
            EvidenciaSaida(
                tipo="mock_simulacao",
                resumo="Relatorio sintetico gerado pelo agente mock; evidencia SIMULADA.",
                simulada=True,
                artefato="relatorio.json",
            )
        )
        return r

    def _res(self, estado: str, resumo: str, t0: float) -> ResultadoAgente:
        return ResultadoAgente(
            estado=estado,  # type: ignore[arg-type]
            resumo=resumo,
            agente_id=self.id,
            mock=True,
            consumo=ConsumoMedicao(latencia_ms=int((time.monotonic() - t0) * 1000), fonte="simulado"),
        )
