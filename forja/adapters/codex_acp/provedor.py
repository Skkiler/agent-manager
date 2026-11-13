"""Codex (OpenAI) como segundo agente, pelo MESMO protocolo ACP (adaptador oficial @agentclientprotocol/codex-acp, que sobe o
Codex App Server). Reaproveita todo o provedor do Kiro (mediador de permissoes, orcamentos, verificacao, correcao, escopo) e
troca so o que e especifico do agente:

- SEGURANCA (falha fechada): o Codex nao tem as regras DENY de segredos que a Forja grava no Kiro. Por isso:
  * o processo recebe um ambiente LIMPO (sem variaveis com cara de segredo e sem APP_*/FORJA_*);
  * o Codex so trabalha em pastas SEM arquivos com cara de segredo (.env, chaves, credenciais). Se houver, ou se a varredura nao
    terminar dentro do limite, a tarefa e BLOQUEADA com o motivo (use o Kiro para ela);
  * modo da sessao: somente leitura para planejar/revisar/estudar/coordenar; escrita com aprovacao para executar. Nunca acesso total.
- MODELO: o do proprio Codex (ou APP_CODEX_MODEL); o catalogo de modelos do Kiro nao vale aqui.
- Login: `codex login` (plano ChatGPT). Chave de API por variavel de ambiente NAO chega ao processo (ambiente limpo).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from forja.adapters.kiro_acp.cliente import ClienteAcp
from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp
from forja.agentes.base import ControleExecucao
from forja.dominio.contratos import ResultadoAgente
from forja.ferramentas.verificacao import ambiente_limpo
from forja.seguranca.acoes import caminho_sensivel

LEITURA = ("read-only", "read_only", "readonly", "plan", "ask")
ESCRITA = ("auto", "workspace-write", "agent", "default")  # NUNCA 'full-access'/'danger'
PARTES_LEITURA = {"planejamento", "revisao", "estudo", "coordenacao", "status"}
MAX_ARQUIVOS_VARREDURA = 20_000
DEPENDENCIAS = frozenset({"node_modules", ".venv", "venv", "__pycache__", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache"})


def resolver_codex(configurado: str = "") -> list[str] | None:
    """Comando do adaptador ACP do Codex: APP_CODEX_ACP_COMMAND, `codex-acp` no PATH ou None (desligado)."""
    if configurado:
        partes = configurado.split()
        exe = shutil.which(partes[0])
        return [exe, *partes[1:]] if exe else None
    exe = shutil.which("codex-acp")
    return [exe] if exe else None


def segredos_nas_pastas(pastas: list[Path], limite: int = MAX_ARQUIVOS_VARREDURA) -> tuple[list[str], bool]:
    """(arquivos com cara de segredo, varredura completa?). So nomes relativos; nada e lido."""
    achados: list[str] = []
    vistos = 0
    for raiz in pastas:
        base = raiz.resolve()
        for atual, dirs, nomes in os.walk(base, followlinks=False):
            dirs[:] = [d for d in dirs if d not in DEPENDENCIAS]  # o resto e varrido (inclusive pastas que o indexador ignora)
            for nome in nomes:
                vistos += 1
                if vistos > limite:
                    return achados, False
                rel = (Path(atual) / nome).relative_to(base).as_posix()
                if caminho_sensivel(rel):
                    achados.append(f"{base.name}/{rel}")
    return achados, True


class ProvedorCodexAcp(ProvedorKiroAcp):
    nome = "Codex"

    def __init__(self, comando: list[str] | None, workspace: Path, modelo: str = "", **kw: Any) -> None:
        super().__init__(comando, workspace, id_="codex.acp", **kw)
        self.modelo_padrao = modelo
        self.usar_mcp = False  # MCP da Forja so no Kiro por enquanto (sinal de prontidao e especifico do Kiro)

    def executar(self, tarefa: dict[str, Any], checkpoint: dict[str, Any], ctl: ControleExecucao) -> ResultadoAgente:
        if self.comando is None:
            return ResultadoAgente(estado="bloqueada", resumo="Codex nao configurado.", agente_id=self.id,
                                   pendencias=["codex_ausente: instale o adaptador (npm i -g @agentclientprotocol/codex-acp), rode "
                                               "'codex login' e ligue o Codex em Configuracoes > Consumo"])
        return super().executar(tarefa, checkpoint, ctl)

    # ------------------------------------------------------------------ ganchos de seguranca
    def _ambiente_processo(self) -> dict[str, str] | None:
        return ambiente_limpo()

    def _presets(self, nivel: str) -> list[str]:
        return []  # presets sao do Kiro

    def _sessao_carregada_segura(self, cliente: ClienteAcp) -> bool:
        return True  # a seguranca do Codex nao depende de modo: depende das pastas (conferidas antes de cada sessao)

    def _modo_codex(self, cliente: ClienteAcp, sid: str, parte: str) -> str | None:
        oferecidos = cliente.modos()
        for nome in (LEITURA if parte in PARTES_LEITURA else ESCRITA):
            if nome in oferecidos:
                cliente.definir_opcao(sid, "mode", nome, self.timeout_handshake)
                cliente.modo_forja = nome  # type: ignore[attr-defined]
                return nome
        return None

    def _aplicar_seguranca(self, cliente: ClienteAcp, sid: str, presets: list[str], trabalho: list[Path], consulta: list[Path],
                           tarefa: dict[str, Any], ctl: ControleExecucao, t0: float) -> ResultadoAgente | None:
        pastas = [*trabalho, *consulta]
        if pastas:
            achados, completa = segredos_nas_pastas(pastas)
            if achados or not completa:
                ctl.evento("codex.bloqueado_segredos", {"arquivos": len(achados), "varredura_completa": completa})
                return self._res("bloqueada", "O Codex nao roda em pastas com arquivos de segredo.", t0, pendencias=[
                    f"codex_bloqueado_segredos: {len(achados)} arquivo(s) com cara de segredo nas pastas do projeto "
                    f"(ex.: {', '.join(achados[:3]) or 'varredura incompleta'}). O Codex nao tem as regras de bloqueio que a Forja "
                    "aplica no Kiro.", "Use o Kiro para esta tarefa ou tire os segredos das pastas do projeto."])
        modo = self._modo_codex(cliente, sid, self._parte_inicial(tarefa))
        ctl.evento("kiro.perfil", {"modo": modo, "agente": "codex", "aplicado": bool(modo)})
        if modo is None and cliente.modos():  # oferece modos, mas nenhum conhecido: o padrao pode ser acesso total
            return self._res("bloqueada", "O Codex nao ofereceu um modo seguro conhecido.", t0, pendencias=[
                f"codex_modo_desconhecido: modos oferecidos {', '.join(cliente.modos())[:200]}; esperado um de "
                f"{', '.join(LEITURA + ESCRITA)}. Atualize o adaptador ou use o Kiro."])
        return None

    def _trocar_modo(self, cliente: ClienteAcp, sid: str, parte: str, ctl: ControleExecucao) -> None:
        atual = getattr(cliente, "modo_forja", None)
        alvo = LEITURA if parte in PARTES_LEITURA else ESCRITA
        if atual in alvo:
            return
        novo = self._modo_codex(cliente, sid, parte)
        if novo:
            ctl.evento("kiro.perfil", {"modo": novo, "agente": "codex", "troca": True})

    def _modo_turno_rapido(self, cliente: ClienteAcp, sid: str, parte: str) -> None:
        self._modo_codex(cliente, sid, "status")

    def configuracao_da_execucao(self, tarefa: dict[str, Any], parte: str | None = None) -> tuple[str, str]:
        return self.modelo_padrao, ""

    def _alternativas(self, tarefa: dict[str, Any], parte: str | None = None) -> list[str]:
        return []
