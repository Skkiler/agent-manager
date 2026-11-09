"""Aprovacoes por acao agrupada (decisao, lote, expiracao). Mixin de `Servico` (usa seus helpers)."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import Tx, novo_id
from forja.agentes.base import ControleExecucao
from forja.dominio.contratos import DecisaoAprovacaoIn, DecisaoLoteIn
from forja.dominio.erros import (
    Conflito,
    ErroDominio,
    NaoEncontrado,
    ValidacaoDominio,
)
from forja.dominio.estados import EstadoExecucao, EstadoTarefa
from forja.observabilidade.sanitizar import sanitizar

ET, EE = EstadoTarefa, EstadoExecucao

log = logging.getLogger("forja.servico")


class _Espera:
    """Ponte entre a thread do worker (aguardando) e a thread da API (decidindo)."""

    def __init__(self) -> None:
        self.evento = threading.Event()
        self.decisao: dict[str, Any] = {"aprovados": [], "adendo": "", "lembrar": False}


class AprovacoesMixin:
    # ------------------------------------------------------------------ aprovacoes
    def decidir_aprovacao(self, aprovacao_id: str, d: DecisaoAprovacaoIn, ator: str = "operador") -> dict:
        """Uma decisao por GRUPO de acoes. Aceita itens parciais, adendo e 'lembrar na execucao'."""
        sinal: tuple[str, dict[str, Any]] | None = None
        reiniciar_execucao: str | None = None
        with self.repo.escrita() as t:
            ap = t.obter(T.Aprovacao, aprovacao_id)
            if ap is None:
                raise NaoEncontrado(f"Aprovacao {aprovacao_id} nao encontrada.")
            if ap["estado"] != "pendente":
                raise Conflito(f"Aprovacao ja decidida ({ap['estado']}).")
            ex = t.obter(T.Execucao, ap["execucao_id"])
            tarefa = t.obter(T.Tarefa, ap["tarefa_id"])
            adendo = d.adendo.strip()
            ts = self._ts()
            if ap["origem"] == "durante_execucao":
                ids = [i["id"] for i in (ap["itens"] or [])]
                if d.itens_aprovados is not None and not set(d.itens_aprovados) <= set(ids):
                    raise ValidacaoDominio("itens_aprovados contem ids que nao pertencem a este pedido.")
                aprovados: list[str] = []
                if d.decisao == "aprovada":
                    aprovados = ids if d.itens_aprovados is None else list(d.itens_aprovados)
                lembrar = bool(d.lembrar_na_execucao and aprovados)
                estado = "aprovada" if aprovados else "negada"
                t.atualizar(
                    T.Aprovacao,
                    aprovacao_id,
                    estado=estado,
                    decidido_por=ator,
                    decidido_em=ts,
                    adendo=adendo,
                    justificativa=d.justificativa or ap["justificativa"],
                    escopo={"aprovados": aprovados, "lembrar": lembrar},
                )
                self._ev(
                    t,
                    f"aprovacao.{estado}",
                    tarefa,
                    ex["id"],
                    {
                        "aprovacao_id": aprovacao_id,
                        "ator": ator,
                        "aprovados": len(aprovados),
                        "negados": len(ids) - len(aprovados),
                        "com_adendo": bool(adendo),
                        "lembrar": lembrar,
                    },
                )
                self._retomar_apos_decisao(t, tarefa, ex, ator)
                sinal = (aprovacao_id, {"aprovados": aprovados, "adendo": adendo, "lembrar": lembrar})
            else:
                t.atualizar(
                    T.Aprovacao,
                    aprovacao_id,
                    estado=d.decisao,
                    decidido_por=ator,
                    decidido_em=ts,
                    adendo=adendo,
                    justificativa=d.justificativa or ap["justificativa"],
                )
                self._ev(
                    t,
                    f"aprovacao.{d.decisao}",
                    tarefa,
                    ex["id"],
                    {"aprovacao_id": aprovacao_id, "ator": ator, "com_adendo": bool(adendo)},
                )
                if d.decisao == "aprovada":
                    self._mudar(t, tarefa, ET.EXECUTANDO, "aprovada", ator)
                    t.atualizar(T.Execucao, ex["id"], estado=EE.EXECUTANDO.value)
                    reiniciar_execucao = ex["id"]
                else:
                    t.atualizar(T.Execucao, ex["id"], estado=EE.CANCELADA.value, finalizado_em=ts)
                    self._mudar(t, tarefa, ET.CANCELADA, "aprovacao negada", ator)
            resultado = t.obter(T.Aprovacao, aprovacao_id)
        if sinal is not None:  # somente apos o commit: o agente nunca age antes de a decisao estar persistida
            with self._mu:
                espera = self._esperas.get(sinal[0])
            if espera is not None:
                espera.decisao = sinal[1]
                espera.evento.set()
        if reiniciar_execucao:
            self._submeter(reiniciar_execucao)
        return resultado

    def _retomar_apos_decisao(self, t: Tx, tarefa: dict, ex: dict, ator: str) -> None:
        """Volta a 'executando' somente quando nao restar nenhum pedido pendente desta execucao."""
        restantes = [a for a in t.listar(T.Aprovacao, execucao_id=ex["id"], estado="pendente")]
        if restantes:
            return
        atual = t.obter(T.Tarefa, tarefa["id"])
        if atual["estado"] == ET.AGUARDANDO_APROVACAO.value:
            self._mudar(t, atual, ET.EXECUTANDO, "decisao registrada; execucao prossegue", ator)
        if ex["estado"] == EE.AGUARDANDO_APROVACAO.value:
            t.atualizar(T.Execucao, ex["id"], estado=EE.EXECUTANDO.value)

    def decidir_lote(self, d: DecisaoLoteIn, ator: str = "operador") -> dict:
        """Aplica UMA decisao a varios pedidos (um clique, um adendo). Falhas individuais nao abortam o resto."""
        resultados, erros = [], []
        for aid in dict.fromkeys(d.ids):
            try:
                resultados.append(
                    self.decidir_aprovacao(
                        aid,
                        DecisaoAprovacaoIn(
                            decisao=d.decisao, adendo=d.adendo, lembrar_na_execucao=d.lembrar_na_execucao
                        ),
                        ator,
                    )
                )
            except ErroDominio as e:
                erros.append({"id": aid, "erro": e.codigo, "mensagem": e.mensagem})
        return {"resultados": resultados, "erros": erros}

    def _solicitar_durante(
        self, execucao_id: str, ctl: ControleExecucao, itens: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Chamado pela thread do worker: cria UM pedido para o grupo de acoes e bloqueia ate a decisao."""
        negar = {"aprovados": [], "adendo": "", "lembrar": False}
        with self.repo.escrita() as t:
            ex = t.obter(T.Execucao, execucao_id)
            tarefa = t.obter(T.Tarefa, ex["tarefa_id"])
            itens_s = sanitizar(itens)
            resumo = "; ".join(i["descricao"] for i in itens_s)[:500]
            ap = t.inserir(
                T.Aprovacao,
                id=novo_id("AP"),
                tarefa_id=tarefa["id"],
                execucao_id=execucao_id,
                acao=f"{len(itens_s)} acao(oes) solicitada(s) pelo agente",
                justificativa=resumo,
                estado="pendente",
                origem="durante_execucao",
                itens=itens_s,
                adendo="",
                criado_em=self._ts(),
            )
            if tarefa["estado"] == ET.EXECUTANDO.value:
                self._mudar(t, tarefa, ET.AGUARDANDO_APROVACAO, "aguardando decisao do operador")
            t.atualizar(T.Execucao, execucao_id, estado=EE.AGUARDANDO_APROVACAO.value)
            self._ev(
                t,
                "aprovacao.solicitada",
                tarefa,
                execucao_id,
                {
                    "aprovacao_id": ap["id"],
                    "acoes": [i["descricao"] for i in itens_s],
                    "riscos": [i["risco"] for i in itens_s],
                },
            )
        espera = _Espera()
        with self._mu:
            self._esperas[ap["id"]] = espera
        limite = time.monotonic() + self.espera_aprovacao_s
        try:
            while not espera.evento.wait(0.2):
                if ctl.cancelado() or ctl.pausado():  # cancelamento/expiracao/shutdown: _finalizar encerra o pedido
                    return negar
                if time.monotonic() > limite:
                    self._expirar_pedido(ap["id"], execucao_id)
                    return negar
            return espera.decisao
        finally:
            with self._mu:
                self._esperas.pop(ap["id"], None)

    def _expirar_pedido(self, aprovacao_id: str, execucao_id: str) -> None:
        with self.repo.escrita() as t:
            ap = t.obter(T.Aprovacao, aprovacao_id)
            if ap is None or ap["estado"] != "pendente":
                return
            ex = t.obter(T.Execucao, execucao_id)
            tarefa = t.obter(T.Tarefa, ex["tarefa_id"])
            t.atualizar(
                T.Aprovacao,
                aprovacao_id,
                estado="negada",
                decidido_por="sistema:timeout",
                decidido_em=self._ts(),
                escopo={"aprovados": [], "lembrar": False},
            )
            self._ev(t, "aprovacao.expirada", tarefa, execucao_id, {"aprovacao_id": aprovacao_id})
            self._retomar_apos_decisao(t, tarefa, ex, "sistema")
