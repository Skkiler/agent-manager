"""Contexto (memoria -> prompt) e conversa agente <-> desenvolvedor. Mixin de `Servico` (usa seus helpers)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import Tx, novo_id
from forja.dominio.contratos import ConversaIn, ResultadoAgente
from forja.dominio.erros import (
    ErroDominio,
    NaoEncontrado,
)
from forja.dominio.estados import EstadoExecucao, EstadoTarefa
from forja.observabilidade.sanitizar import redigir_segredos, sanitizar

ET, EE = EstadoTarefa, EstadoExecucao

log = logging.getLogger("forja.servico")


class ConversaContextoMixin:
    # ------------------------------------------------------------------ contexto (memoria -> prompt, com orcamento)
    def _dados_de_retomada(self, t: Tx, tarefa: dict, execucao_id: str) -> dict[str, Any] | None:
        """Se esta execucao ja conversou antes, devolve o MINIMO para retomar: entendimento curto, decisoes propostas e
        as respostas do desenvolvedor. Nao reenvia a resposta anterior inteira (economia de tokens)."""
        msgs = t.listar(T.Mensagem, ordem=T.Mensagem.ordem, tarefa_id=tarefa["id"], limite=500)
        if not any(m["execucao_id"] == execucao_id and m["papel"] == "agente" for m in msgs):
            return None
        decisoes = next((m for m in reversed(msgs) if m["papel"] == "agente" and m["tipo"] == "decisoes"), None)
        corte = decisoes["ordem"] if decisoes else 0
        entend = next(
            (m["conteudo"] for m in reversed(msgs) if m["papel"] == "agente" and m["tipo"] == "entendimento"), ""
        )
        return {
            "entendimento": " ".join(entend.split())[:420],
            "decisoes": ((decisoes or {}).get("dados") or {}).get("decisoes", []),
            "respostas": [m["conteudo"] for m in msgs if m["papel"] == "operador" and m["ordem"] > corte],
        }

    def _montar_contexto(self, execucao_id: str, tarefa: dict) -> Any | None:
        """Monta o pacote de contexto e o grava (o que entrou, quanto custou, o que foi omitido). Nunca derruba a execucao."""
        if self.construtor_contexto is None:
            return None
        try:
            if tarefa.get("retomada") is not None:  # retomada: so o que foi USADO na rodada anterior
                with self.repo.leitura() as t:
                    uso = t.listar(T.ContextoUso, execucao_id=execucao_id, limite=1)
                if uso:
                    tarefa["contexto_texto"] = self.construtor_contexto.so_uteis(uso[0]["itens"], uso[0]["uteis"] or [])
                return None
            pacote = self.construtor_contexto.construir(tarefa)
            tarefa["contexto_texto"] = pacote.texto
            with self.repo.escrita() as t:
                t.inserir(
                    T.ContextoUso,
                    id=novo_id("CTX"),
                    tarefa_id=tarefa["id"],
                    execucao_id=execucao_id,
                    itens=[i.como_dict() for i in pacote.itens],
                    tokens_contexto=pacote.tokens,
                    tokens_prompt=0,
                    orcamento=pacote.orcamento,
                    omitidos=pacote.omitidos,
                    termos=pacote.termos,
                    uteis=None,
                    criado_em=self._ts(),
                )
                self._ev(
                    t,
                    "contexto.montado",
                    tarefa,
                    execucao_id,
                    {
                        "itens": len(pacote.itens),
                        "tokens_estimados": pacote.tokens,
                        "orcamento": pacote.orcamento,
                        "omitidos": pacote.omitidos,
                    },
                )
            return pacote
        except Exception:  # noqa: BLE001 - contexto e otimizacao: falhar aqui nao pode impedir a tarefa
            log.exception("falha ao montar contexto", extra={"execucao_id": execucao_id})
            return None

    def _registrar_uteis(self, execucao_id: str, pacote: Any | None, res: ResultadoAgente) -> None:
        """Marca quais itens de contexto a resposta realmente USOU (citacao [M1] ou id/arquivo) e o tamanho do prompt."""
        if pacote is None or pacote.vazio:
            return
        try:
            texto = " ".join([a.conteudo for a in res.artefatos] + [m.conteudo for m in res.mensagens])
            uteis = self.construtor_contexto.marcar_uteis(pacote, texto)
            with self.repo.escrita() as t:
                linhas = t.listar(T.ContextoUso, execucao_id=execucao_id, limite=1)
                if linhas:
                    t.atualizar(
                        T.ContextoUso, linhas[0]["id"], uteis=uteis, tokens_prompt=res.consumo.tokens_input or 0
                    )
                ex = t.obter(T.Execucao, execucao_id)
                self._ev(
                    t,
                    "contexto.uteis",
                    t.obter(T.Tarefa, ex["tarefa_id"]),
                    execucao_id,
                    {"injetados": len(pacote.itens), "usados": len(uteis)},
                )
        except Exception:  # noqa: BLE001
            log.exception("falha ao registrar utilidade do contexto", extra={"execucao_id": execucao_id})

    def contexto_da_tarefa(self, tarefa_id: str) -> list[dict]:
        self.obter(T.Tarefa, tarefa_id)
        with self.repo.leitura() as t:
            return t.listar(T.ContextoUso, tarefa_id=tarefa_id)

    # ------------------------------------------------------------------ conversa agente <-> desenvolvedor
    @staticmethod
    def _proxima_ordem(t: Tx, tarefa_id: str) -> int:
        return (
            int(
                t.s.scalar(
                    select(func.coalesce(func.max(T.Mensagem.ordem), 0)).where(T.Mensagem.tarefa_id == tarefa_id)
                )
                or 0
            )
            + 1
        )

    def conversa(self, tarefa_id: str) -> list[dict]:
        self.obter(T.Tarefa, tarefa_id)
        with self.repo.leitura() as t:
            return t.listar(T.Mensagem, ordem=T.Mensagem.ordem, tarefa_id=tarefa_id, limite=1000)

    def responder(self, tarefa_id: str, d: ConversaIn, ator: str = "operador") -> dict[str, Any]:
        """Registra a resposta livre do desenvolvedor e, se couber, retoma a execucao que aguardava as decisoes."""
        texto = redigir_segredos(d.conteudo).strip()
        with self.repo.escrita() as t:
            tarefa = t.obter(T.Tarefa, tarefa_id)
            if tarefa is None:
                raise NaoEncontrado(f"Tarefa {tarefa_id} nao encontrada.")
            msg = t.inserir(
                T.Mensagem,
                id=novo_id("MSG"),
                tarefa_id=tarefa_id,
                ordem=self._proxima_ordem(t, tarefa_id),
                execucao_id=None,
                papel="operador",
                tipo="resposta_operador",
                conteudo=texto,
                dados=None,
                criado_em=self._ts(),
            )
            self._ev(t, "conversa.resposta_do_operador", tarefa, None, {"mensagem_id": msg["id"], "ator": ator})
            pausadas = [e for e in t.listar(T.Execucao, tarefa_id=tarefa_id, estado=EE.PAUSADA.value)]
        resultado: dict[str, Any] = {"mensagem": msg, "retomada_execucao_id": None, "aviso": None}
        if not d.retomar:
            return resultado
        if not pausadas or tarefa["estado"] != ET.BLOQUEADA.value:
            resultado["aviso"] = "resposta registrada; nao ha execucao aguardando para retomar."
            return resultado
        try:
            self.iniciar_execucao(pausadas[-1]["id"], ator)
            resultado["retomada_execucao_id"] = pausadas[-1]["id"]
        except ErroDominio as e:  # ex.: duplo clique, deadline expirado, orcamento de tentativas
            resultado["aviso"] = f"resposta registrada, mas a retomada nao ocorreu: {e.mensagem}"
        return resultado

    def _persistir_mensagens(self, t: Tx, tarefa: dict, execucao_id: str, res: ResultadoAgente) -> None:
        if not res.mensagens:
            return
        ordem = self._proxima_ordem(t, tarefa["id"])
        for m in res.mensagens:
            t.inserir(
                T.Mensagem,
                id=novo_id("MSG"),
                tarefa_id=tarefa["id"],
                ordem=ordem,
                execucao_id=execucao_id,
                papel="agente",
                tipo=m.tipo,
                conteudo=redigir_segredos(m.conteudo),
                dados=sanitizar(m.dados) if m.dados else None,
                criado_em=self._ts(),
            )
            ordem += 1
        decisoes = [m for m in res.mensagens if m.tipo == "decisoes"]
        self._ev(
            t,
            "conversa.mensagens_do_agente",
            tarefa,
            execucao_id,
            {
                "secoes": [m.tipo for m in res.mensagens],
                "decisoes_pendentes": len((decisoes[0].dados or {}).get("decisoes", [])) if decisoes else 0,
            },
        )
