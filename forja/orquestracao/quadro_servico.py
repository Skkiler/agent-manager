"""Quadro de comunicacao (blackboard) e painel de controle do master.

Mensagens tipadas, priorizadas, idempotentes (por origem + dedup_key) e com validade. O quadro guarda resumo factual e
REFERENCIAS (memoria, artefato, evidencia), nunca historico de conversa. Sem HTTP; persiste pelo repositorio.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite, novo_id
from forja.dominio.erros import Conflito, NaoEncontrado
from forja.dominio.quadro import EstadoMensagem, MensagemIn
from forja.dominio.tempo import Relogio, RelogioSistema, iso, somar
from forja.observabilidade.sanitizar import redigir_segredos, sanitizar

EM = EstadoMensagem
ABERTAS = (EM.PENDENTE.value, EM.ENTREGUE.value)
URGENTE = 2  # prioridade <= 2 entra nos alertas do master
PARADA_APOS_S = 1800


def _ordenar(msgs: list[dict]) -> list[dict]:
    return sorted(msgs, key=lambda m: (m["prioridade"], m["criado_em"], m["id"]))


class QuadroServico:
    def __init__(self, repo: RepositorioSqlite, relogio: Relogio | None = None) -> None:
        self.repo = repo
        self.relogio = relogio or RelogioSistema()

    def _agora(self) -> str:
        return iso(self.relogio.agora())

    # ------------------------------------------------------------------ publicar
    def publicar(self, d: MensagemIn, ator: str = "operador") -> tuple[dict, bool]:
        """Devolve (mensagem, criada). Reenvio com a mesma origem+dedup_key devolve a original (criada=False)."""
        try:
            return self._publicar(d, ator)
        except IntegrityError:  # corrida entre dois reenvios identicos: vence o primeiro
            existente = self._por_dedup(d.origem, d.dedup_key)
            if existente is None:
                raise
            return existente, False

    def _por_dedup(self, origem: str, dedup_key: str | None) -> dict | None:
        if not dedup_key:
            return None
        with self.repo.leitura() as t:
            achados = t.listar(T.MensagemQuadro, origem=origem, dedup_key=dedup_key, limite=1)
        return achados[0] if achados else None

    def _publicar(self, d: MensagemIn, ator: str) -> tuple[dict, bool]:
        existente = self._por_dedup(d.origem, d.dedup_key)
        if existente:
            return existente, False
        agora = self.relogio.agora()
        with self.repo.escrita() as t:
            tarefa = t.obter(T.Tarefa, d.tarefa_id) if d.tarefa_id else None
            if d.tarefa_id and tarefa is None:
                raise NaoEncontrado(f"Tarefa {d.tarefa_id} nao encontrada.")
            msg = t.inserir(
                T.MensagemQuadro,
                id=novo_id("QD"),
                versao=1,
                origem=d.origem,
                destino=d.destino,
                tipo=d.tipo.value,
                prioridade=d.prioridade,
                assunto=redigir_segredos(d.assunto),
                payload=sanitizar(d.payload),
                referencias=list(d.referencias),
                tarefa_id=d.tarefa_id,
                estado=EM.PENDENTE.value,
                dedup_key=d.dedup_key,
                correlation_id=(tarefa or {}).get("correlation_id") or uuid.uuid4().hex,
                criado_em=iso(agora),
                expira_em=iso(somar(agora, d.expira_em_segundos)) if d.expira_em_segundos else None,
                nota_resolucao="",
            )
            # O evento (SSE) leva so ids/estado: nunca assunto nem payload.
            t.emitir_evento(
                "quadro.mensagem_publicada", iso(agora),
                {"mensagem_id": msg["id"], "tipo": msg["tipo"], "prioridade": msg["prioridade"],
                 "destino": msg["destino"], "ator": ator},
                projeto_id=(tarefa or {}).get("projeto_id"), tarefa_id=d.tarefa_id,
                correlation_id=msg["correlation_id"],
            )
        return msg, True

    # ------------------------------------------------------------------ consultar / retirar
    def expirar(self) -> int:
        """Marca como expiradas as mensagens abertas cuja validade passou. Idempotente."""
        agora = self._agora()
        n = 0
        with self.repo.escrita() as t:
            for estado in ABERTAS:
                for m in t.listar(T.MensagemQuadro, estado=estado, limite=2000):
                    if m["expira_em"] and m["expira_em"] <= agora:
                        t.atualizar(T.MensagemQuadro, m["id"], estado=EM.EXPIRADA.value)
                        n += 1
        return n

    def listar(self, destino: str | None = None, estado: str | None = None, tipo: str | None = None,
               prioridade_max: int | None = None, limite: int = 50) -> list[dict]:
        self.expirar()
        filtros: dict[str, Any] = {k: v for k, v in (("estado", estado), ("tipo", tipo)) if v}
        with self.repo.leitura() as t:
            if destino:
                msgs = t.listar(T.MensagemQuadro, destino=destino, limite=2000, **filtros)
                if destino != "todos":
                    msgs += t.listar(T.MensagemQuadro, destino="todos", limite=2000, **filtros)
            else:
                msgs = t.listar(T.MensagemQuadro, limite=2000, **filtros)
        if prioridade_max:
            msgs = [m for m in msgs if m["prioridade"] <= prioridade_max]
        return _ordenar(msgs)[:limite]

    def retirar(self, destino: str, limite: int = 10) -> list[dict]:
        """Entrega as pendentes de `destino` por prioridade e as marca 'entregue' (cada uma e entregue uma so vez).
        Difusoes ('todos') sao devolvidas mas nao consumidas: cada destinatario as le sem tirar a dos outros."""
        self.expirar()
        agora = self._agora()
        with self.repo.escrita() as t:
            proprias = _ordenar(t.listar(T.MensagemQuadro, destino=destino, estado=EM.PENDENTE.value, limite=2000))
            difusao = t.listar(T.MensagemQuadro, destino="todos", estado=EM.PENDENTE.value, limite=2000)
            escolhidas = _ordenar(proprias + (difusao if destino != "todos" else []))[:limite]
            for m in escolhidas:
                if m["destino"] == destino:
                    t.atualizar(T.MensagemQuadro, m["id"], estado=EM.ENTREGUE.value, entregue_em=agora)
        return escolhidas

    def resolver(self, mensagem_id: str, ator: str = "operador", nota: str = "") -> dict:
        agora = self._agora()
        with self.repo.escrita() as t:
            m = t.obter(T.MensagemQuadro, mensagem_id)
            if m is None:
                raise NaoEncontrado(f"Mensagem {mensagem_id} nao encontrada.")
            if m["estado"] not in ABERTAS:
                raise Conflito(f"Mensagem ja esta '{m['estado']}'.")
            t.atualizar(T.MensagemQuadro, mensagem_id, estado=EM.RESOLVIDA.value, resolvida_em=agora,
                        resolvida_por=ator, nota_resolucao=redigir_segredos(nota))
            t.emitir_evento("quadro.mensagem_resolvida", agora, {"mensagem_id": mensagem_id, "ator": ator},
                            tarefa_id=m["tarefa_id"], correlation_id=m["correlation_id"])
            return t.obter(T.MensagemQuadro, mensagem_id) or m

    # ------------------------------------------------------------------ monitoramento
    def painel_controle(self, parada_apos_s: int = PARADA_APOS_S) -> dict[str, Any]:
        """Visao compacta para o master: o que exige atencao agora, em ordem de prioridade."""
        self.expirar()
        agora_dt = self.relogio.agora()
        agora = iso(agora_dt)
        limite_parada = iso(somar(agora_dt, -parada_apos_s))
        with self.repo.leitura() as t:
            abertas = [m for e in ABERTAS for m in t.listar(T.MensagemQuadro, estado=e, limite=2000)]
            por_estado = dict(t.s.execute(select(T.Tarefa.estado, func.count()).group_by(T.Tarefa.estado)).all())
            bloqueadas = t.listar(T.Tarefa, estado="bloqueada", limite=50)
            aprovacoes = t.listar(T.Aprovacao, estado="pendente", limite=50)
            em_curso = [e for est in ("executando", "pausada", "aguardando_aprovacao")
                        for e in t.listar(T.Execucao, estado=est, limite=200)]
        urgentes = _ordenar([m for m in abertas if m["prioridade"] <= URGENTE])
        paradas = [e for e in em_curso
                   if (e["deadline"] and e["deadline"] < agora)
                   or (e["estado"] == "executando" and e["iniciado_em"] and e["iniciado_em"] < limite_parada)]
        alertas = []
        if urgentes:
            alertas.append(f"{len(urgentes)} mensagem(ns) urgente(s) aberta(s) no quadro")
        if bloqueadas:
            alertas.append(f"{len(bloqueadas)} tarefa(s) bloqueada(s) aguardando decisao")
        if aprovacoes:
            alertas.append(f"{len(aprovacoes)} aprovacao(oes) pendente(s)")
        if paradas:
            alertas.append(f"{len(paradas)} execucao(oes) vencida(s) ou sem progresso ha mais de {parada_apos_s}s")

        def resumo(m: dict) -> dict:
            return {k: m[k] for k in ("id", "origem", "destino", "tipo", "prioridade", "assunto", "tarefa_id",
                                      "criado_em", "expira_em")}

        return {
            "gerado_em": agora,
            "alertas": alertas,
            "quadro": {
                "abertas": len(abertas),
                "por_prioridade": dict(sorted(Counter(m["prioridade"] for m in abertas).items())),
                "urgentes": [resumo(m) for m in urgentes[:10]],
            },
            "tarefas": {"por_estado": por_estado,
                        "aguardando_decisao": [{"id": b["id"], "titulo": b["titulo"]} for b in bloqueadas[:10]]},
            "aprovacoes_pendentes": [{"id": a["id"], "acao": a["acao"]} for a in aprovacoes[:10]],
            "execucoes_paradas": [{"id": e["id"], "tarefa_id": e["tarefa_id"], "estado": e["estado"],
                                   "deadline": e["deadline"], "iniciado_em": e["iniciado_em"]} for e in paradas[:10]],
        }

