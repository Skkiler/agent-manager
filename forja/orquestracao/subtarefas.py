"""Subagentes em paralelo: o plano de uma tarefa complexa dividido em subtarefas independentes.

Quando o turno de planejamento devolve '## Subtarefas' (2 a 4 partes), o provedor para ANTES de executar e entrega a lista
numa mensagem tipada. Este gancho (pos-execucao) cria, no mesmo objetivo:
- uma tarefa por parte (nivel 'normal' forcado: subtarefa nao se divide de novo);
- uma tarefa de CONSOLIDACAO que depende de todas, com os criterios da tarefa original (junta e confere os resultados).
Preferencia 'subagentes': 'propor' deixa tudo no Backlog para revisao; 'executar' prepara e inicia as partes em paralelo
(cada uma reserva a pasta; se ocupada, git worktree num branch proprio) e inicia a consolidacao quando todas concluirem.
Idempotente por execucao (dedup), limitado (MAX) e sem recursao.
"""

from __future__ import annotations

import logging
from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.conversa.briefing import MAX_SUBTAREFAS
from forja.dominio.contratos import Politicas, ResultadoAgente, TarefaIn, TransicaoIn
from forja.dominio.estados import EstadoTarefa

log = logging.getLogger("forja.subtarefas")
ET = EstadoTarefa


class SubtarefasServico:
    def __init__(self, servico: Any) -> None:
        self.servico = servico
        self.modo = "propor"  # desligado | propor | executar (preferencia 'subagentes')

    def ao_finalizar(self, execucao_id: str, res: ResultadoAgente) -> None:
        try:
            msg = next((m for m in res.mensagens if m.tipo == "subtarefas"), None)
            if msg is not None and self.modo != "desligado":
                self._criar(execucao_id, (msg.dados or {}).get("subtarefas") or [])
            self._iniciar_consolidacoes(execucao_id)
        except Exception:  # noqa: BLE001 - ganchos nunca alteram o resultado da execucao
            log.exception("falha ao tratar subtarefas", extra={"execucao_id": execucao_id})

    def _criar(self, execucao_id: str, subs: list[dict[str, Any]]) -> list[str]:
        s = self.servico
        ex = s.obter(T.Execucao, execucao_id)
        pai = s.obter(T.Tarefa, ex["tarefa_id"])
        if (pai.get("entrada") or {}).get("subtarefa_de"):
            return []  # sem recursao
        subs = [x for x in subs if isinstance(x, dict) and x.get("titulo")][:MAX_SUBTAREFAS]
        if len(subs) < 2:
            return []
        politicas = Politicas(**{**(pai.get("politicas") or {}), "complexidade": "normal"})
        filhos = []
        for i, sub in enumerate(subs, start=1):
            d = TarefaIn(objetivo_id=pai["objetivo_id"], titulo=f"[{i}/{len(subs)}] {sub['titulo']}"[:200],
                         descricao=(f"Parte {i} de {len(subs)} da tarefa '{pai['titulo']}'. Faca SO esta parte: "
                                    f"{sub.get('descricao') or sub['titulo']}\nNao altere o que pertence as outras partes.")[:4000],
                         criterios_aceite=[f"parte entregue: {sub['titulo']}"[:300]], modo=pai["modo"], especialidade=pai["especialidade"],
                         politicas=politicas, entrada={"subtarefa_de": pai["id"], "parte": i})
            t, _ = s.criar_tarefa(d, chave=f"sub-{execucao_id}-{i}")
            filhos.append(t)
        branches = ", ".join(f"forja/{f['id']}-*" for f in filhos)
        cons, _ = s.criar_tarefa(TarefaIn(
            objetivo_id=pai["objetivo_id"], titulo=f"[consolidar] {pai['titulo']}"[:200],
            descricao=(f"Junte e confira o resultado das {len(filhos)} subtarefas de '{pai['titulo']}'. Se alguma rodou numa copia "
                       f"isolada, o trabalho dela esta num branch ({branches}): integre-o. Rode a verificacao completa.\n\n"
                       f"Tarefa original: {pai.get('descricao') or ''}")[:4000],
            criterios_aceite=list(pai.get("criterios_aceite") or ["resultado integrado e verificado"]), modo=pai["modo"],
            especialidade=pai["especialidade"], dependencias=[f["id"] for f in filhos], politicas=politicas,
            entrada={"subtarefa_de": pai["id"], "consolida": pai["id"], "modo_subagentes": self.modo}), chave=f"sub-{execucao_id}-c")
        s._emitir_avulso("subtarefas.criadas", pai["id"], execucao_id,
                         {"subtarefas": [f["id"] for f in filhos], "consolidacao": cons["id"], "modo": self.modo})
        for t in [*filhos, cons]:
            self._preparar(t)
        if self.modo == "executar":
            for f in filhos:
                self._executar(f["id"])
        return [f["id"] for f in filhos]

    def _preparar(self, tarefa: dict) -> None:
        s = self.servico
        if tarefa["estado"] != ET.RASCUNHO.value:
            return
        a, _ = s.transicionar(tarefa["id"], TransicaoIn(para=ET.CLASSIFICADA, expected_version=tarefa["versao_estado"],
                                                        motivo="subtarefa do plano"), ator="sistema:subtarefas")
        if self.modo == "executar":
            s.transicionar(tarefa["id"], TransicaoIn(para=ET.PREPARADA, expected_version=a["versao_estado"], motivo="subtarefa do plano"),
                           ator="sistema:subtarefas")

    def _executar(self, tarefa_id: str) -> None:
        s = self.servico
        try:
            if s.obter(T.Tarefa, tarefa_id)["estado"] != ET.PRONTA.value:
                return
            ex = s.criar_execucao(tarefa_id)
            s.iniciar_execucao(ex["id"], ator="sistema:subtarefas")
        except Exception as e:  # noqa: BLE001 - a subtarefa fica pronta para executar a mao
            log.info("subtarefa nao iniciou: %s", type(e).__name__, extra={"tarefa_id": tarefa_id})

    def _iniciar_consolidacoes(self, execucao_id: str) -> None:
        """Quando a ultima parte conclui, a consolidacao fica 'pronta' (dependencias); no modo executar ela inicia sozinha."""
        s = self.servico
        ex = s.obter(T.Execucao, execucao_id)
        tarefa = s.obter(T.Tarefa, ex["tarefa_id"])
        pai = (tarefa.get("entrada") or {}).get("subtarefa_de")
        if not pai or (tarefa.get("entrada") or {}).get("consolida"):
            return
        for c in s.listar(T.Tarefa, projeto_id=tarefa["projeto_id"], estado=ET.PRONTA.value):
            entrada = c.get("entrada") or {}
            if entrada.get("consolida") == pai and entrada.get("modo_subagentes") == "executar":
                self._executar(c["id"])
