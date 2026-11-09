"""Atualizacao do segundo cerebro a partir de tarefas concluidas (item 3.10).

Deterministico, sem LLM: monta uma memoria CANDIDATA com fonte e referencias. Nunca valida sozinha: a promocao
(`verificado` -> `validado`) continua exigindo evidencia real e a decisao explicita do operador.
"""

from __future__ import annotations

from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.dominio.erros import Conflito, NaoEncontrado
from forja.memoria.contratos import FonteIn, MemoriaIn
from forja.memoria.modelo import Principal
from forja.orquestracao.memoria_servico import ServicoMemoria
from forja.orquestracao.servico import Servico

MAX_EVIDENCIAS = 5
MAX_RESUMO = 1500


class PropostasMemoria:
    def __init__(self, servico: Servico, memoria: ServicoMemoria) -> None:
        self.servico = servico
        self.memoria = memoria

    def propor_de_tarefa(self, p: Principal, tarefa_id: str, namespace: str, ator: str = "operador") -> dict[str, Any]:
        """Cria (ou devolve, se ja existir) a memoria candidata da tarefa. Idempotente por `tarefa:<id>` em `refs`."""
        p.exigir(namespace)
        with self.servico.repo.leitura() as t:
            tarefa = t.obter(T.Tarefa, tarefa_id)
            if tarefa is None:
                raise NaoEncontrado(f"Tarefa {tarefa_id} nao encontrada.")
            if tarefa["estado"] != "concluida":
                raise Conflito(f"So tarefas concluidas geram proposta (estado atual: {tarefa['estado']}).")
            evidencias = t.listar(T.Evidencia, tarefa_id=tarefa_id, limite=100)
            execucoes = [e for e in t.listar(T.Execucao, tarefa_id=tarefa_id, limite=50) if e["estado"] == "concluida"]
        ref = f"tarefa:{tarefa_id}"
        existente = self._existente(p, namespace, ref)
        if existente:
            return {"memoria": existente, "criada": False, "avisos": ["proposta ja existente para esta tarefa"]}

        reais = [e for e in evidencias if not e["simulada"]]
        simuladas = len(evidencias) - len(reais)
        resumo_exec = ((execucoes[-1].get("resultado") or {}).get("resumo") or "") if execucoes else ""
        partes = [f"## Objetivo\n{tarefa['descricao'] or tarefa['titulo']}"]
        if tarefa["criterios_aceite"]:
            partes.append("## Criterios de aceite\n" + "\n".join(f"- {c}" for c in tarefa["criterios_aceite"]))
        if resumo_exec:
            partes.append("## Resultado\n" + resumo_exec[:MAX_RESUMO])
        if evidencias:
            partes.append("## Evidencias\n" + "\n".join(
                f"- {e['tipo']}{' (SIMULADA)' if e['simulada'] else ''}: {e['resumo'][:200]}"
                for e in evidencias[:MAX_EVIDENCIAS]))
        avisos = []
        if simuladas:
            avisos.append(f"{simuladas} evidencia(s) simulada(s) nao foram vinculadas e nao sustentam validacao")
        if not reais:
            avisos.append("sem evidencia real: a memoria so podera avancar apos evidencia real posterior")

        m = self.memoria.criar(p, MemoriaIn(
            tipo="procedimental",
            titulo=f"Procedimento: {tarefa['titulo']}"[:200],
            resumo=(tarefa["descricao"] or tarefa["titulo"])[:300],
            conteudo="\n\n".join(partes),
            namespace=namespace,
            fonte=FonteIn(tipo="execucao", caminho=f"tarefas/{tarefa_id}"),
            precondicoes=[],
            tags=["proposta", "automatica", tarefa["especialidade"]][:30],
            refs=[ref, *[f"evidencia:{e['id']}" for e in reais[:MAX_EVIDENCIAS]]],
            confianca=0.0,
        ), ator)
        for e in reais[:MAX_EVIDENCIAS]:
            m = self.memoria.vincular_evidencia(p, m["id"], e["id"], ator)
        return {"memoria": m, "criada": True, "avisos": avisos}

    def _existente(self, p: Principal, namespace: str, ref: str) -> dict[str, Any] | None:
        with self.servico.repo.leitura() as t:
            for m in t.listar(T.Memoria, namespace=namespace, limite=2000):
                if ref in (m["refs"] or []) and m["estado"] not in ("revogado", "substituido"):
                    return self.memoria.obter(p, m["id"])
        return None
