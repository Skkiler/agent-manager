"""ProvedorAgente real sobre Kiro ACP V3. Fase 2: somente leitura/analise, permissoes negadas por padrao.

Honestidade: a resposta do Kiro e texto de um LLM. Ela vira artefato e evidencia do tipo 'kiro_resposta'
(simulada=False), mas NAO e verificada por teste deterministico; a validacao de aceite continua sendo do orquestrador.
O consumo de tokens nao e exposto pelo ACP: registrado como 'indisponivel' (nunca estimado).
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

from forja.adapters.kiro_acp.cliente import (
    AcpAutenticacaoNecessaria,
    AcpCliAusente,
    AcpDesconectado,
    AcpErro,
    AcpProtocoloNaoSuportado,
    AcpTimeout,
    ClienteAcp,
    DecisorPermissao,
    decisor_negar_tudo,
)
from forja.agentes.base import ControleExecucao
from forja.dominio.contratos import ArtefatoSaida, ConsumoMedicao, EvidenciaSaida, ResultadoAgente
from forja.observabilidade.sanitizar import sanitizar_texto

log = logging.getLogger("forja.kiro")
MAX_RESPOSTA = 200_000
MAX_EVENTOS_TOOL = 100
MODOS_PERMITIDOS = {"analise", "documentacao"}


def resolver_cli(configurado: str = "") -> str | None:
    """Localiza o kiro-cli sem shell: caminho configurado, PATH, depois local padrao do Windows."""
    candidatos = [configurado] if configurado else ["kiro-cli"]
    for c in candidatos:
        achado = shutil.which(c)
        if achado:
            return achado
    if not configurado:
        base = os.environ.get("LOCALAPPDATA")
        if base:
            for pasta in ("Kiro-Cli", "kiro-cli"):
                p = Path(base) / pasta / "kiro-cli.exe"
                if p.is_file():
                    return str(p)
    return None


def montar_comando(cli: str, agente: str = "", modelo: str = "", engine: str = "v3") -> list[str]:
    cmd = [cli, "acp", f"--agent-engine={engine}"]
    if agente:
        cmd += ["--agent", agente]
    if modelo:
        cmd += ["--model", modelo]
    return cmd  # nunca inclui --trust-all-tools / --trust-tools


def montar_prompt(tarefa: dict[str, Any]) -> str:
    criterios = "\n".join(f"- {c}" for c in tarefa.get("criterios_aceite", []))
    return (
        "Voce e um agente de ANALISE SOMENTE LEITURA executando uma tarefa da plataforma Forja.\n"
        "Nao modifique arquivos, nao execute comandos de escrita, nao acesse segredos ou credenciais.\n"
        "Responda em portugues com: resumo, evidencias, hipoteses (marcadas como tal) e pendencias.\n\n"
        f"Tarefa: {tarefa['titulo']}\n"
        f"Descricao: {tarefa.get('descricao') or '(sem descricao)'}\n"
        f"Criterios de aceite:\n{criterios}\n"
    )


class ProvedorKiroAcp:
    mock = False

    def __init__(
        self,
        comando: list[str] | None,
        workspace: Path,
        timeout_prompt: float = 300.0,
        decisor_permissao: DecisorPermissao = decisor_negar_tudo,
        id_: str = "kiro.acp.v3",
        timeout_handshake: float = 30.0,
    ) -> None:
        self.comando = comando
        self.workspace = workspace
        self.timeout_prompt = timeout_prompt
        self.timeout_handshake = timeout_handshake
        self._decisor = decisor_permissao
        self.id = id_

    # --------------------------------------------------------------------------------
    def executar(self, tarefa: dict[str, Any], checkpoint: dict[str, Any], ctl: ControleExecucao) -> ResultadoAgente:
        t0 = time.monotonic()
        if tarefa.get("modo") not in MODOS_PERMITIDOS:
            return self._res("falhou", f"Modo '{tarefa.get('modo')}' nao habilitado no provedor Kiro (Fase 2: somente "
                             f"{sorted(MODOS_PERMITIDOS)}).", t0)
        if self.comando is None:
            return self._res("bloqueada", "Kiro CLI nao encontrado.", t0,
                             pendencias=["kiro_cli_ausente: instale o Kiro CLI ou configure APP_KIRO_CLI_PATH"])
        self.workspace.mkdir(parents=True, exist_ok=True)

        partes: list[str] = []
        n_tools = 0

        def on_update(_sid: str, upd: dict[str, Any]) -> None:
            nonlocal n_tools
            tipo = upd.get("sessionUpdate")
            if tipo == "agent_message_chunk":
                c = upd.get("content") or {}
                if c.get("type") == "text" and sum(map(len, partes)) < MAX_RESPOSTA:
                    partes.append(str(c.get("text", "")))
            elif tipo in ("tool_call", "tool_call_update") and n_tools < MAX_EVENTOS_TOOL:
                n_tools += 1
                ctl.evento("kiro.ferramenta", {"titulo": str(upd.get("title", ""))[:200],
                           "tipo": upd.get("kind"), "status": upd.get("status")})

        cliente = ClienteAcp(self.comando, cwd=str(self.workspace), decisor_permissao=self._decisor,
                             on_update=on_update)
        sid: str | None = None
        try:
            cliente.iniciar()
            cliente.inicializar(self.timeout_handshake)
            ctl.evento("kiro.conectado", {"agente": cliente.agent_info.get("name"),
                                          "versao": cliente.agent_info.get("version")})
            sid = cliente.nova_sessao(str(self.workspace.resolve()), self.timeout_handshake)
            ctl.registrar_checkpoint({"sessao": "criada"})
            fut = cliente.requisitar("session/prompt", {"sessionId": sid,
                                     "prompt": [{"type": "text", "text": montar_prompt(tarefa)}]})
            parada = self._aguardar(cliente, fut, sid, ctl)
            texto = sanitizar_texto("".join(partes)) if partes else ""
            if parada == "interrompido":
                return self._res("cancelada" if ctl.cancelado() else "pausada",
                                 "Execucao interrompida pelo orquestrador.", t0)
            return self._concluir(parada, texto, cliente, n_tools, t0)
        except AcpAutenticacaoNecessaria as e:
            return self._res("bloqueada", "Autenticacao do Kiro necessaria.", t0,
                             pendencias=["reautenticacao_necessaria: execute 'kiro-cli login' no desktop", e.mensagem])
        except AcpCliAusente:
            return self._res("bloqueada", "Kiro CLI nao encontrado.", t0, pendencias=["kiro_cli_ausente"])
        except AcpTimeout as e:
            return self._res("falhou", f"Timeout: {e.mensagem}", t0)
        except AcpProtocoloNaoSuportado as e:
            return self._res("falhou", e.mensagem, t0, pendencias=["protocolo_acp_incompativel"])
        except AcpDesconectado:
            return self._res("falhou", "Conexao ACP perdida durante a execucao.", t0,
                             pendencias=[f"stderr: {cliente.stderr_recente()[:300]}"])
        except AcpErro as e:
            return self._res("falhou", f"Erro ACP: {e.mensagem}", t0)
        finally:
            cliente.encerrar()

    def _aguardar(self, cliente: ClienteAcp, fut, sid: str, ctl: ControleExecucao) -> str:
        """Espera o prompt sem bloquear cancelamento/pausa. Retorna stopReason ou 'interrompido'."""
        limite = time.monotonic() + self.timeout_prompt
        cancelou = False
        while True:
            if (ctl.cancelado() or ctl.pausado()) and not cancelou:
                cancelou = True
                cliente.cancelar(sid)  # ACP nao tem 'pausa': cancela o turno; checkpoint permite reenviar
                limite = min(limite, time.monotonic() + 10)
            if fut.done():
                res = fut.result()
                return "interrompido" if cancelou else str(res.get("stopReason", "end_turn"))
            if time.monotonic() > limite:
                cliente.cancelar(sid)
                raise AcpTimeout(f"session/prompt excedeu {self.timeout_prompt:.0f}s.")
            time.sleep(0.05)

    def _concluir(self, parada: str, texto: str, cliente: ClienteAcp, n_tools: int, t0: float) -> ResultadoAgente:
        if parada == "refusal":
            return self._res("falhou", "O modelo recusou a solicitacao (refusal).", t0, chamadas=1)
        if not texto.strip():
            return self._res("falhou", f"Kiro finalizou ({parada}) sem conteudo de resposta.", t0, chamadas=1)
        r = self._res("concluida", f"Resposta do Kiro recebida (stopReason={parada}).", t0, chamadas=1)
        r.artefatos.append(ArtefatoSaida(nome="resposta_kiro.md", tipo="texto", conteudo=texto))
        r.evidencias.append(EvidenciaSaida(
            tipo="kiro_resposta", simulada=False, artefato="resposta_kiro.md",
            resumo=f"Resposta de LLM via ACP (nao verificada deterministicamente). Ferramentas observadas: {n_tools}; "
                   f"permissoes negadas: {cliente.permissoes_negadas}."))
        if parada == "max_tokens":
            r.pendencias.append("resposta_truncada: stopReason=max_tokens")
        r.hipoteses.append("Conteudo da resposta e gerado por modelo; requer revisao antes de uso.")
        return r

    def _res(self, estado: str, resumo: str, t0: float, pendencias: list[str] | None = None,
             chamadas: int = 0) -> ResultadoAgente:
        return ResultadoAgente(
            estado=estado,  # type: ignore[arg-type]
            resumo=resumo, agente_id=self.id, mock=False, pendencias=pendencias or [],
            consumo=ConsumoMedicao(latencia_ms=int((time.monotonic() - t0) * 1000), chamadas_modelo=chamadas,
                                   fonte="indisponivel"),
        )
