"""Varios agentes (Kiro e Codex) atras da mesma interface: a Forja escolhe quem executa cada tarefa.

- Contextos SEPARADOS por agente: a sessao (e o checkpoint) pertence ao agente que a abriu; uma retomada volta para o mesmo agente.
  O que e compartilhado e so o conhecimento do segundo cerebro (com ACL) e o estado da tarefa.
- Distribuicao (preferencia 'distribuicao_provedores'):
  * inteligente (padrao): por especialidade (decidir_inteligente): complexas, refatoracao, arquitetura, seguranca, interface,
    estudo e coordenacao no Kiro (Claude); simples, status, verificacao, analise/documentacao normais e revisoes (segunda opiniao
    de outra familia de modelo) no Codex (GPT). Cada um e reserva do outro.
  * so_kiro: tudo no Kiro; o Codex nem e consultado.
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
MODOS = ("so_kiro", "inteligente", "auto", "equilibrar", "codex_primeiro")
PARTES_CODEX_EQUILIBRAR = {"rapida", "revisao", "status"}
# Modo 'inteligente' (por especialidade). Base: comparativos publicos de 2026 (ver docs/adr/0024): os dois empatam em benchmarks
# gerais de correcao de bugs; o Claude (Kiro) tende a entregar codigo de mais qualidade em mudancas multi-arquivo, refatoracao e
# planejamento; o GPT (Codex) responde mais rapido, gasta menos tokens e segue instrucoes curtas a risca. Alem disso, so o Kiro tem
# o perfil com regras DENY de segredos, o MCP da Forja (memoria, caderno) e o mediador vendo todos os comandos.
_TERMOS_KIRO = re.compile(r"(?i)\b(arquitetur\w*|refator\w*|migr[ae]\w*|redesenh\w*|reescrev\w*|seguranc\w*|autentica\w*|"
                          r"autoriza\w*|concorren\w*|varios arquivos|multiplos arquivos|frontend|interface|ui\b|ux\b)")


def decidir_inteligente(tarefa: dict[str, Any]) -> tuple[str, str]:
    """('kiro'|'codex', motivo). Deterministico e explicavel (o motivo vai para o evento 'provedor.escolhido')."""
    rota = classificar(tarefa)
    modo = tarefa.get("modo") or "analise"
    entrada = tarefa.get("entrada") or {}
    texto = f"{tarefa.get('titulo', '')} {tarefa.get('descricao') or ''}"
    if modo == "estudo" or rota.parte in ("estudo", "coordenacao"):
        return "kiro", "estudo/coordenacao usam o MCP e o protocolo do Kiro"
    if rota.parte == "revisao" or entrada.get("revisao"):
        autor = str((entrada.get("revisao") or {}).get("autor") or "") if isinstance(entrada.get("revisao"), dict) else ""
        if autor.startswith("codex"):
            return "kiro", "revisao cruzada: quem revisa e de outra familia de modelo que quem fez"
        return "codex", "revisao por outra familia de modelo (segunda opiniao independente)"
    if rota.nivel == "complexa" or rota.planejar:
        return "kiro", "tarefa complexa (planejamento + execucao multi-arquivo)"
    if _TERMOS_KIRO.search(texto):
        return "kiro", "tema que pede mais qualidade em mudanca ampla (arquitetura, refatoracao, seguranca, interface)"
    if rota.nivel == "simples" or rota.parte in ("rapida", "status"):
        return "codex", "tarefa simples: mais rapida e barata no Codex com esforco baixo"
    if modo == "verificacao":
        return "codex", "verificacao/diagnostico de testes: instrucao curta e objetiva"
    if modo in ("analise", "documentacao"):
        return "codex", "analise/documentacao normal: somente leitura ou texto, custo menor"
    return "kiro", "alteracao de codigo normal: qualidade e mediacao de todos os comandos pela Forja"
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
        self.modo = "inteligente"  # preferencia 'distribuicao_provedores'
        self.codex_ativo = True  # preferencia 'codex_ativo' (so vale com o codex-acp instalado; desligado = o Codex nunca e usado)
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
        return self._ordem_e_motivo(tarefa)[0]

    def _ordem_e_motivo(self, tarefa: dict[str, Any]) -> tuple[list[Any], str]:
        disponiveis = self.agentes()
        if len(disponiveis) == 1 or self.modo == "so_kiro":
            return [self.kiro], "so_kiro" if self.modo == "so_kiro" else "codex desligado ou nao instalado"
        parte = classificar(tarefa).parte
        if self.modo == "inteligente":
            preferido, motivo = decidir_inteligente(tarefa)
            codex_primeiro = preferido == "codex"
        else:
            codex_primeiro = self.modo == "codex_primeiro" or (self.modo == "equilibrar" and parte in PARTES_CODEX_EQUILIBRAR)
            motivo = f"modo {self.modo}"
        ordem = [self.codex, self.kiro] if codex_primeiro else [self.kiro, self.codex]
        return ([p for p in ordem if not self._resfriado(p)] or [self.kiro]), motivo

    def _elegivel(self, prov: Any, tarefa: dict[str, Any]) -> bool:
        if prov is not self.codex:
            return True
        from forja.adapters.codex_acp.provedor import segredos_nas_pastas

        pastas = [Path(p["caminho"]) for p in ((tarefa.get("projeto_ctx") or {}).get("pastas") or [])]
        achados, completa = segredos_nas_pastas(pastas) if pastas else ([], True)
        return completa and not achados

    def executar(self, tarefa: dict[str, Any], checkpoint: dict[str, Any], ctl: ControleExecucao) -> ResultadoAgente:
        anterior = (checkpoint or {}).get("provedor")
        candidatos, motivo = self._ordem_e_motivo(tarefa)
        if tarefa.get("retomada") and anterior:  # contexto separado: a conversa continua no agente que a comecou
            dono = next((p for p in self.agentes() if p.id == anterior), None)
            if dono is not None:
                candidatos = [dono, *[p for p in candidatos if p is not dono]]
                motivo = "retomada: a conversa continua no agente que a comecou"
        elegiveis = [p for p in candidatos if self._elegivel(p, tarefa)] or [self.kiro]
        if self.codex in candidatos and self.codex not in elegiveis:
            motivo += "; Codex fora: pasta com arquivo de segredo (sem copia sem segredos)"
        candidatos = elegiveis
        res: ResultadoAgente | None = None
        for i, prov in enumerate(candidatos):
            ctl.evento("provedor.escolhido", {"agente": prov.id, "modo": self.modo, "reserva": i > 0, "motivo": motivo[:200]})
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
        codex_antes = self.modo in ("equilibrar", "codex_primeiro", "inteligente") and self.codex in self.agentes()
        ordem = [self.codex, self.kiro] if codex_antes else self.agentes()
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
