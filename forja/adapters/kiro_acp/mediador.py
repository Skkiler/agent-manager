"""Mediador de permissoes: transforma N pedidos de ferramenta do Kiro em UMA pergunta de aprovacao por grupo de acoes.

Regras:
- Acoes sensiveis (segredos/credenciais) sao negadas AUTOMATICAMENTE, sem perguntar (invariante de seguranca).
- Pedidos que chegam dentro de uma janela curta sao agrupados em um unico pedido ao operador.
- Uma aprovacao pode ser "lembrada" ate o fim da execucao (mesma categoria + alvos): evita perguntar de novo.
- Nunca escolhe `allow_always` do Kiro: a memoria de decisoes e da Forja, auditavel e limitada a execucao.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from forja.agentes.base import ControleExecucao
from forja.seguranca.acoes import descrever_acao

log = logging.getLogger("forja.mediador")


def _opcao(opcoes: list[dict[str, Any]], *tipos: str) -> str | None:
    for tipo in tipos:
        for o in opcoes:
            if str(o.get("kind", "")) == tipo:
                return str(o.get("optionId"))
    return None


def _rejeitar(opcoes: list[dict[str, Any]]) -> str | None:
    achada = _opcao(opcoes, "reject_once")
    if achada:
        return achada
    for o in opcoes:
        if str(o.get("kind", "")).startswith("reject"):
            return str(o.get("optionId"))
    return None  # sem opcao de rejeicao: o cliente responde 'cancelled'


class _Lote:
    def __init__(self) -> None:
        self.itens: list[dict[str, Any]] = []
        self.pronto = threading.Event()
        self.aprovados: set[str] = set()
        self.lembrar = False


class MediadorPermissoes:
    def __init__(self, ctl: ControleExecucao, workspace: Path, janela: float = 0.8, espera_max: float = 1800.0) -> None:
        self.ctl = ctl
        self.workspace = workspace
        self.janela = janela
        self.espera_max = espera_max
        self.adendos: list[str] = []
        self.perguntas = 0  # quantas vezes o operador foi realmente consultado
        self._lote: _Lote | None = None
        self._mu = threading.Lock()
        self._lembradas: set[str] = set()

    @staticmethod
    def _chave(item: dict[str, Any]) -> str:
        return f"{item['categoria']}|{','.join(sorted(item['alvos']))}"

    def decidir(self, pedido: dict[str, Any]) -> str | None:
        """Implementa DecisorPermissao. Retorna optionId (ou None => cancelar)."""
        opcoes = pedido.get("options", [])
        item = descrever_acao(pedido.get("toolCall") or {}, self.workspace)
        rejeitar = _rejeitar(opcoes)
        permitir = _opcao(opcoes, "allow_once")
        if item["sensivel"]:
            self.ctl.evento("kiro.permissao_negada_automatica",
                            {"motivo": "acao envolve segredo/credencial", "descricao": item["descricao"]})
            return rejeitar
        if permitir is None:  # sem como permitir uma vez: nao arrisca allow_always
            return rejeitar
        if self._chave(item) in self._lembradas:
            self.ctl.evento("kiro.permissao_reutilizada", {"descricao": item["descricao"]})
            return permitir
        return permitir if self._perguntar(item) else rejeitar

    def _perguntar(self, item: dict[str, Any]) -> bool:
        with self._mu:
            lider = self._lote is None
            if lider:
                self._lote = _Lote()
            lote = self._lote
            assert lote is not None
            lote.itens.append(item)
        if lider:
            time.sleep(self.janela)  # coleta pedidos concorrentes
            with self._mu:
                self._lote = None  # fecha o lote; novos pedidos abrem outro
            try:
                self.perguntas += 1
                decisao = self.ctl.solicitar_aprovacao(lote.itens)
                lote.aprovados = set(decisao.get("aprovados", []))
                lote.lembrar = bool(decisao.get("lembrar"))
                if decisao.get("adendo"):
                    self.adendos.append(str(decisao["adendo"]))
                if lote.lembrar:
                    self._lembradas.update(self._chave(i) for i in lote.itens if i["id"] in lote.aprovados)
            except Exception:  # noqa: BLE001 - falha ao perguntar = negar
                log.exception("falha ao solicitar aprovacao; negando grupo")
                lote.aprovados = set()
            finally:
                lote.pronto.set()
        else:
            lote.pronto.wait(timeout=self.espera_max)
        return item["id"] in lote.aprovados
