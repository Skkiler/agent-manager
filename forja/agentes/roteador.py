"""Varios agentes (Kiro e Codex) atras da mesma interface: a Forja escolhe quem executa cada tarefa.

- Contextos SEPARADOS por agente: a sessao (e o checkpoint) pertence ao agente que a abriu; uma retomada volta para o mesmo agente.
  O que e compartilhado e so o conhecimento do segundo cerebro (com ACL) e o estado da tarefa.
- Distribuicao (preferencia 'distribuicao_provedores'):
  * so_kiro (padrao): tudo no Kiro; o Codex nem e consultado.
  * auto: Kiro primeiro; o Codex e reserva quando o Kiro esta indisponivel (sem CLI, sem login, modelo ausente, limite de uso).
  * equilibrar: tarefas simples, revisoes e resumos no Codex; o resto no Kiro (cada um e reserva do outro). Divide o uso entre
    os dois planos.
  * codex_primeiro: Codex primeiro, Kiro de reserva.
- Reserva so quando o agente falhou ANTES de produzir trabalho (nada de texto): nunca repete uma tarefa que ja mexeu em arquivos.
  O agente que falhou por indisponibilidade fica 15 min de 'resfriamento'.
- O Codex so e elegivel em pastas sem arquivos com cara de segredo (adapters/codex_acp).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from forja.agentes.base import ControleExecucao
from forja.dominio.contratos import ResultadoAgente
from forja.orquestracao.roteamento import classificar

log = logging.getLogger("forja.roteador")
MODOS = ("so_kiro", "auto", "equilibrar", "codex_primeiro")
PARTES_CODEX_EQUILIBRAR = {"rapida", "revisao", "status"}
RESFRIAMENTO_S = 15 * 60
_INDISPONIVEL = re.compile(r"(?i)(kiro_cli_ausente|codex_ausente|reautenticacao|modelo_indisponivel|rate.?limit|usage limit|quota|"
                           r"\bcota\b|\b429\b|limite de uso|too many requests)")


class _CtlComProvedor:
    """Repassa tudo ao controle original, mas carimba o agente no checkpoint (a sessao e daquele agente)."""

    def __init__(self, ctl: ControleExecucao, provedor_id: str) -> None:
        self._ctl, self._id = ctl, provedor_id

    def registrar_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        self._ctl.registrar_checkpoint({**checkpoint, "provedor": self._id})

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._ctl, nome)


class ProvedoresRoteados:
    id = "forja.roteador"

    def __init__(self, kiro: Any, codex: Any | None = None) -> None:
        self.kiro = kiro
        self.codex = codex
        self.modo = "so_kiro"
        self.codex_ativo = False  # preferencia 'codex_ativo' (desligado: o Codex nunca e usado)
        self._resfriando: dict[str, float] = {}
        self._mu = threading.Lock()

    @property
    def mock(self) -> bool:
        return bool(getattr(self.kiro, "mock", False))

    def __getattr__(self, nome: str) -> Any:  # compatibilidade: atributos de leitura do agente principal (ex.: max_ferramentas)
        if nome.startswith("_"):
            raise AttributeError(nome)
        return getattr(self.kiro, nome)

    def agentes(self) -> list[Any]:
        return [self.kiro, *([self.codex] if self.codex is not None and self.codex_ativo and self.codex.comando else [])]

    def _resfriado(self, prov: Any) -> bool:
        with self._mu:
            ate = self._resfriando.get(prov.id, 0)
        return ate > time.monotonic()

    def ordem(self, tarefa: dict[str, Any]) -> list[Any]:
        disponiveis = self.agentes()
        if len(disponiveis) == 1 or self.modo == "so_kiro":
            return [self.kiro]
        parte = classificar(tarefa).parte
        codex_primeiro = self.modo == "codex_primeiro" or (self.modo == "equilibrar" and parte in PARTES_CODEX_EQUILIBRAR)
        ordem = [self.codex, self.kiro] if codex_primeiro else [self.kiro, self.codex]
        return [p for p in ordem if not self._resfriado(p)] or [self.kiro]

    def _elegivel(self, prov: Any, tarefa: dict[str, Any]) -> bool:
        if prov is not self.codex:
            return True
        from forja.adapters.codex_acp.provedor import segredos_nas_pastas

        pastas = [Path(p["caminho"]) for p in ((tarefa.get("projeto_ctx") or {}).get("pastas") or [])]
        achados, completa = segredos_nas_pastas(pastas) if pastas else ([], True)
        return completa and not achados

    def executar(self, tarefa: dict[str, Any], checkpoint: dict[str, Any], ctl: ControleExecucao) -> ResultadoAgente:
        anterior = (checkpoint or {}).get("provedor")
        candidatos = self.ordem(tarefa)
        if tarefa.get("retomada") and anterior:  # contexto separado: a conversa continua no agente que a comecou
            dono = next((p for p in self.agentes() if p.id == anterior), None)
            if dono is not None:
                candidatos = [dono, *[p for p in candidatos if p is not dono]]
        candidatos = [p for p in candidatos if self._elegivel(p, tarefa)] or [self.kiro]
        res: ResultadoAgente | None = None
        for i, prov in enumerate(candidatos):
            ctl.evento("provedor.escolhido", {"agente": prov.id, "modo": self.modo, "reserva": i > 0})
            cp = checkpoint if (checkpoint or {}).get("provedor", prov.id) == prov.id else {}
            res = prov.executar(tarefa, cp, _CtlComProvedor(ctl, prov.id))  # type: ignore[arg-type]
            if not self._indisponivel(res) or i == len(candidatos) - 1 or ctl.cancelado() or ctl.pausado():
                return res
            with self._mu:
                self._resfriando[prov.id] = time.monotonic() + RESFRIAMENTO_S
            ctl.evento("provedor.reserva", {"de": prov.id, "motivo": (res.pendencias or [res.resumo])[0][:160]})
        return res  # type: ignore[return-value]

    @staticmethod
    def _indisponivel(res: ResultadoAgente) -> bool:
        if res.estado not in ("bloqueada", "falhou") or (res.consumo.tokens_output or 0) > 0 or res.artefatos:
            return False  # ja produziu trabalho: nunca repetir em outro agente
        return bool(_INDISPONIVEL.search(" ".join([res.resumo, *res.pendencias])))

    def turno_rapido(self, texto: str, parte: str = "status", timeout: float = 120.0) -> str:
        ordem = [self.codex, self.kiro] if self.modo in ("equilibrar", "codex_primeiro") and self.codex in self.agentes() else self.agentes()
        erro: Exception | None = None
        for prov in ordem:
            if self._resfriado(prov) or not hasattr(prov, "turno_rapido"):
                continue
            try:
                return prov.turno_rapido(texto, parte, timeout)
            except Exception as e:  # noqa: BLE001 - tenta o proximo agente
                erro = e
        raise erro or RuntimeError("nenhum agente disponivel")

    def estado(self) -> dict[str, Any]:
        agora = time.monotonic()
        return {"modo": self.modo, "agentes": [
            {"id": p.id, "configurado": bool(getattr(p, "comando", None)), "ativo": p in self.agentes(),
             "resfriando_s": max(0, int(self._resfriando.get(p.id, 0) - agora))}
            for p in [self.kiro, *([self.codex] if self.codex is not None else [])]]}
