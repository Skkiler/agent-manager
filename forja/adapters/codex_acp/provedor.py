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

import json
import shutil
from pathlib import Path
from typing import Any

from forja.adapters.kiro_acp import perfil_kiro
from forja.adapters.kiro_acp.cliente import ClienteAcp
from forja.adapters.kiro_acp.provedor import ProvedorKiroAcp
from forja.agentes.base import ControleExecucao
from forja.dominio.contratos import ResultadoAgente
from forja.ferramentas.verificacao import ambiente_limpo
from forja.seguranca.acoes import descrever_acao
from forja.seguranca.sensiveis import (  # noqa: F401 - reexportados (compatibilidade)
    GLOBS,
    MAX_ARQUIVOS_VARREDURA,
    segredos_nas_pastas,
)

LEITURA = ("read-only", "read_only", "readonly", "plan", "ask")
# codex-acp 2.7.0 (sondado): read-only | workspace-write | agent ("Auto review": o proprio Codex aprova) | agent-full-access.
# So entram modos em que as permissoes voltam para a Forja: NUNCA 'agent' (auto aprovacao) nem acesso total.
ESCRITA = ("workspace-write", "auto")
PARTES_LEITURA = {"planejamento", "revisao", "estudo", "coordenacao", "status"}
MODOS_ESCRITA = {"alteracao_codigo", "documentacao", "verificacao"}  # modos de tarefa que podem escrever na pasta de trabalho
# Esforco de raciocinio por parte (codex-acp: opcao 'reasoning_effort'). Sem isto tudo rodava no padrao da conta ('high'):
# 72 s numa correcao trivial que o Kiro fez em 27 s. Rapido/status/coordenacao nao precisam de raciocinio longo.
REGRA_PASTAS = ("PASTAS (regra absoluta): trabalhe SO dentro das pastas do projeto citadas neste pedido. Nao leia, liste nem busque "
                "nada fora delas (pasta pessoal, outros projetos, configuracoes do sistema): a Forja cancela o turno se voce tentar.\n"
                "TESTES: a Forja roda os testes e o lint do projeto ao final e devolve o resultado; nao gaste tempo tentando rodar "
                "python/testes no seu sandbox (nesta maquina eles costumam nao estar disponiveis la).\n")
ESFORCO_PADRAO = {"rapida": "low", "status": "low", "coordenacao": "low", "execucao": "medium", "estudo": "medium",
                  "planejamento": "high", "revisao": "high"}


def resolver_codex(configurado: str = "") -> list[str] | None:
    """Comando do adaptador ACP do Codex: APP_CODEX_ACP_COMMAND, `codex-acp` no PATH ou None (desligado)."""
    if configurado:
        partes = configurado.split()
        exe = shutil.which(partes[0])
        return [exe, *partes[1:]] if exe else None
    exe = shutil.which("codex-acp")
    return [exe] if exe else None


ENV_EXCLUIR = ["*TOKEN*", "*SECRET*", "*PASSWORD*", "*PASSWD*", "*SENHA*", "*API_KEY*", "*APIKEY*", "*ACCESS_KEY*", "*PRIVATE*",
               "*CREDENTIAL*", "*COOKIE*", "*SESSION*", "*AUTH*", "FORJA_*", "APP_*"]


PASTAS_PESSOAIS_NEGADAS = (".ssh", ".aws", ".gnupg", ".kube", ".docker")


def perfil_permissoes() -> dict[str, Any]:
    """Perfil de permissao NATIVO do Codex (sandbox do proprio Codex): o modo ':workspace' + DENY para os mesmos globs de segredo do
    perfil do Kiro e para as pastas de credenciais da pasta pessoal. Sondado no codex-acp 2.7.0/Windows (ADR-026): aceito e
    aplicado de verdade (um arquivo inocente listado como deny deixou de ser lido). Rejeitados na sonda: ':root' deny (sessao
    recusada com 'Internal error') e '~' deny (session/new nao respondeu). Leitura FORA da pasta continua possivel no modo de
    escrita: a vigia da Forja cobre esse caso."""
    return {"extends": ":workspace", "filesystem": {
        "glob_scan_max_depth": 4, **{f"~/{d}": "deny" for d in PASTAS_PESSOAIS_NEGADAS},
        ":workspace_roots": {g: "deny" for g in GLOBS}}}


def configuracao_sessao() -> dict[str, Any]:
    """Configuracao da sessao do Codex no nivel do perfil do Kiro: regras como instrucao de desenvolvedor, ambiente minimo e
    perfil de permissao nativo com DENY de segredos."""
    return {
        "developer_instructions": ("Voce trabalha para a Forja, um orquestrador local. " + perfil_kiro.ESCOPO + "\n" + REGRA_PASTAS
                                   + "Se uma regra acima impedir o pedido, NAO tente contornar: explique em '## Decisões para você'."),
        "shell_environment_policy": {"inherit": "core", "exclude": ENV_EXCLUIR},
        "default_permissions": "forja",
        "permissions": {"forja": perfil_permissoes()},
    }


def _leitura_proibida(upd: dict[str, Any], raizes: list[Path]) -> str | None:
    """Vigia em tempo real: chamada do Codex que cita segredo ou caminho FORA das pastas do projeto. O sandbox 'read-only' do Codex
    le o disco quase inteiro sem pedir nada (achado real + doc da OpenAI), e o perfil de permissao nativo nega segredos mas nao
    consegue negar a raiz (':root' deny derruba a sessao no codex-acp 2.7.0/Windows). A Forja cancela o turno ao ver a chamada."""
    if upd.get("sessionUpdate") != "tool_call":
        return None
    item = descrever_acao(upd, raizes[0] if raizes else None, raizes[1:], [])
    if item["sensivel"]:
        return f"codex_segredo_bloqueado: a chamada '{item['tecnico'][:80]}' envolve arquivo ou variavel de segredo"
    if raizes and item["fora_do_workspace"]:
        return f"codex_fora_da_pasta_bloqueado: a chamada '{item['tecnico'][:80]}' acessa um caminho fora das pastas do projeto"
    return None


class ProvedorCodexAcp(ProvedorKiroAcp):
    nome = "Codex"

    def __init__(self, comando: list[str] | None, workspace: Path, modelo: str = "", **kw: Any) -> None:
        super().__init__(comando, workspace, id_="codex.acp", **kw)
        self.modelo_padrao = modelo
        self.usar_mcp = False  # MCP da Forja: mesma preferencia do Kiro (kiro_mcp_ativo); testado com o codex-acp 2.7.0
        self.esforco_de = None  # o mapa de esforco do Kiro nao vale aqui (valores e modelos diferentes); ver ESFORCO_PADRAO

    def executar(self, tarefa: dict[str, Any], checkpoint: dict[str, Any], ctl: ControleExecucao) -> ResultadoAgente:
        if self.comando is None:
            return ResultadoAgente(estado="bloqueada", resumo="Codex nao configurado.", agente_id=self.id,
                                   pendencias=["codex_ausente: instale o adaptador (npm i -g @agentclientprotocol/codex-acp), rode "
                                               "'codex login' e ligue o Codex em Configuracoes > Consumo"])
        return super().executar(tarefa, checkpoint, ctl)

    # ------------------------------------------------------------------ ganchos de seguranca
    def _ambiente_processo(self) -> dict[str, str] | None:
        """Ambiente limpo + CODEX_CONFIG (mesclado pelo codex-acp na config da sessao). Testado no codex-acp 2.7.0:
        - developer_instructions: as regras da Forja entram como instrucao de DESENVOLVEDOR (prioridade acima do pedido). Medido:
          pedido para ler arquivo fora da pasta -> o proprio Codex recusou, sem nenhuma chamada de ferramenta (a vigia nem precisou
          agir). E o 'se policiar' pedido pelo usuario;
        - shell_environment_policy: comandos do Codex herdam so o ambiente basico e nunca variaveis com cara de segredo.
        - permissions/default_permissions: perfil proprio que estende ':workspace' com DENY de segredos (ver perfil_permissoes).
        Rejeitados no teste: approval_policy (aposentado pela OpenAI; quebra a sessao), perfis com ':root' deny (sessao recusada)
        e hooks PreToolUse (a confianca foi gravada, mas o gancho nao rodou pelo adaptador)."""
        return {**ambiente_limpo(), "CODEX_CONFIG": json.dumps(configuracao_sessao(), ensure_ascii=True)}

    def _aguardar_mcp(self, nomes: list[str], estado: dict[str, Any], tokens: list[int], ctl: ControleExecucao) -> tuple[bool, str]:
        return True, "codex_inicia_mcp_na_sessao"  # o codex-acp so responde session/new com os MCPs ja iniciados (medido: 0,3 s)

    def _presets(self, nivel: str) -> list[str]:
        return []  # presets sao do Kiro

    def _sessao_carregada_segura(self, cliente: ClienteAcp) -> bool:
        return True  # a seguranca do Codex nao depende de modo: depende das pastas (conferidas antes de cada sessao)

    def _modo_codex(self, cliente: ClienteAcp, sid: str, parte: str) -> str | None:
        oferecidos = cliente.modos()
        so_leitura = parte in PARTES_LEITURA or getattr(cliente, "so_leitura_forja", False)
        for nome in (LEITURA if so_leitura else ESCRITA):
            if nome in oferecidos:
                cliente.definir_opcao(sid, "mode", nome, self.timeout_handshake)
                cliente.modo_forja = nome  # type: ignore[attr-defined]
                return nome
        return None

    def _aplicar_seguranca(self, cliente: ClienteAcp, sid: str, presets: list[str], trabalho: list[Path], consulta: list[Path],
                           tarefa: dict[str, Any], ctl: ControleExecucao, t0: float) -> ResultadoAgente | None:
        pastas = [*trabalho, *consulta]
        if pastas:
            achados, completa = tarefa.get("_segredos_pastas") or segredos_nas_pastas(pastas)
            if achados or not completa:
                ctl.evento("codex.bloqueado_segredos", {"arquivos": len(achados), "varredura_completa": completa})
                return self._res("bloqueada", "O Codex nao roda em pastas com arquivos de segredo.", t0, pendencias=[
                    f"codex_bloqueado_segredos: {len(achados)} arquivo(s) com cara de segredo nas pastas do projeto "
                    f"(ex.: {', '.join(achados[:3]) or 'varredura incompleta'}). O perfil nativo do Codex nega esses "
                    "arquivos, mas nao cobre caminhos fora da pasta como as regras do Kiro; por precaucao a Forja nao o usa aqui.", "Use o Kiro para esta tarefa ou tire os segredos das pastas do projeto."])
        # tarefa que nao escreve (analise, estudo...) ou sem pasta de trabalho: somente leitura na sessao inteira
        cliente.so_leitura_forja = tarefa.get("modo") not in MODOS_ESCRITA or not trabalho  # type: ignore[attr-defined]
        modo = self._modo_codex(cliente, sid, self._parte_inicial(tarefa))
        ctl.evento("kiro.perfil", {"modo": modo, "agente": "codex", "aplicado": bool(modo)})
        if modo is None and cliente.modos():  # oferece modos, mas nenhum conhecido: o padrao pode ser acesso total
            return self._res("bloqueada", "O Codex nao ofereceu um modo seguro conhecido.", t0, pendencias=[
                f"codex_modo_desconhecido: modos oferecidos {', '.join(cliente.modos())[:200]}; esperado um de "
                f"{', '.join(LEITURA + ESCRITA)}. Atualize o adaptador ou use o Kiro."])
        return None

    def _trocar_modo(self, cliente: ClienteAcp, sid: str, parte: str, ctl: ControleExecucao) -> None:
        atual = getattr(cliente, "modo_forja", None)
        alvo = LEITURA if parte in PARTES_LEITURA or getattr(cliente, "so_leitura_forja", False) else ESCRITA
        if atual in alvo:
            return
        novo = self._modo_codex(cliente, sid, parte)
        if novo:
            ctl.evento("kiro.perfil", {"modo": novo, "agente": "codex", "troca": True})

    def _modo_turno_rapido(self, cliente: ClienteAcp, sid: str, parte: str) -> None:
        self._modo_codex(cliente, sid, "status")

    def configuracao_da_execucao(self, tarefa: dict[str, Any], parte: str | None = None) -> tuple[str, str]:
        """(modelo, esforco) do Codex para a parte. Modelo: APP_CODEX_MODEL ou o padrao da conta (o catalogo do Kiro nao vale aqui).
        Esforco: preferencia do usuario por parte (esforco_de) ou o mapa ESFORCO_PADRAO; validado contra a sessao ao aplicar."""
        parte = parte or self._parte(tarefa)
        esforco = ""
        try:
            esforco = self.esforco_de(parte) if self.esforco_de else ""
        except Exception:  # noqa: BLE001 - ler preferencia nunca derruba a execucao
            esforco = ""
        return self.modelo_padrao, esforco or ESFORCO_PADRAO.get(parte, "medium")

    def _alternativas(self, tarefa: dict[str, Any], parte: str | None = None) -> list[str]:
        return []

    def _vigiar(self, upd: dict[str, Any], raizes: list[Path]) -> str | None:
        return _leitura_proibida(upd, raizes)

    def _regras_agente(self, tarefa: dict[str, Any]) -> str:
        """O Codex nao tem perfil com regras DENY: a regra completa de segredos vai no pedido, mais o limite das pastas."""
        if tarefa.get("modo") in MODOS_ESCRITA:  # o protocolo de escrita ja traz a regra completa
            return "\n" + REGRA_PASTAS
        return "\n" + perfil_kiro.SEGREDOS_REGRA + "\n" + REGRA_PASTAS
