"""AGENTE MOCK (SIMULADO). Nao chama Kiro nem modelo algum; serve para validar o nucleo.

Cenarios em tarefa.entrada.mock_cenario: sucesso (padrao) | falha | bloqueio | conversa | escrita (cria 1 arquivo sintetico
na pasta de trabalho do projeto, para demonstrar 'desfazer').
Parametros: mock_passos (1..50, padrao 3), mock_passo_ms (0..1000, padrao 0).
Toda evidencia produzida e marcada simulada=True: NAO comprova funcionalidade real.
"""

from __future__ import annotations

import json
import time
from typing import Any

from forja.agentes.base import ControleExecucao
from forja.dominio.contratos import (
    ArtefatoSaida,
    ConsumoMedicao,
    EvidenciaSaida,
    MensagemSaida,
    ResultadoAgente,
)


def _limitar(v: Any, minimo: int, maximo: int, padrao: int) -> int:
    try:
        return max(minimo, min(maximo, int(v)))
    except (TypeError, ValueError):
        return padrao


class AgenteMock:
    id = "mock.deterministico"
    mock = True

    def executar(self, tarefa: dict[str, Any], checkpoint: dict[str, Any], ctl: ControleExecucao) -> ResultadoAgente:
        t0 = time.monotonic()
        entrada = tarefa.get("entrada") or {}
        cenario = str(entrada.get("mock_cenario", "sucesso"))
        passos = _limitar(entrada.get("mock_passos"), 1, 50, 3)
        passo_ms = _limitar(entrada.get("mock_passo_ms"), 0, 1000, 0)
        inicio = int(checkpoint.get("passo", 0))

        for i in range(inicio, passos):
            if ctl.cancelado():
                return self._res("cancelada", "Cancelado durante a simulacao.", t0)
            if ctl.pausado():
                return self._res("pausada", f"Pausado no passo {i}.", t0)
            ctl.dormir(passo_ms / 1000)
            if ctl.cancelado():
                return self._res("cancelada", "Cancelado durante a simulacao.", t0)
            if ctl.pausado():
                return self._res("pausada", f"Pausado no passo {i}.", t0)
            ctl.registrar_checkpoint({"passo": i + 1, "total": passos})
            ctl.evento("agente.passo", {"passo": i + 1, "total": passos, "mock": True})

        if cenario == "conversa":
            return self._conversa(tarefa, t0)
        if cenario == "escrita":
            return self._escrita(tarefa, t0)
        if entrada.get("coordenacao"):
            return self._coordenacao(entrada["coordenacao"], t0)
        if cenario == "falha":
            return self._res("falhou", "Falha simulada solicitada pelo cenario.", t0)
        if cenario == "bloqueio":
            r = self._res("bloqueada", "Bloqueio simulado solicitado pelo cenario.", t0)
            r.pendencias.append("Intervencao manual simulada necessaria.")
            return r

        relatorio = json.dumps(
            {"simulado": True, "tarefa": tarefa["id"], "passos": passos, "criterios": tarefa["criterios_aceite"]},
            ensure_ascii=False,
            sort_keys=True,
        )
        r = self._res("concluida", "Execucao simulada concluida (nenhum trabalho real foi feito).", t0)
        r.artefatos.append(ArtefatoSaida(nome="relatorio.json", tipo="json", conteudo=relatorio))
        r.evidencias.append(
            EvidenciaSaida(
                tipo="mock_simulacao",
                resumo="Relatorio sintetico gerado pelo agente mock; evidencia SIMULADA.",
                simulada=True,
                artefato="relatorio.json",
            )
        )
        return r

    def _conversa(self, tarefa: dict[str, Any], t0: float) -> ResultadoAgente:
        """Simula o fluxo organico: 1a rodada entende, propoe e PEDE decisoes (agrupadas); a retomada conclui."""
        retomada = tarefa.get("retomada")
        if not retomada:
            decisoes = [
                {
                    "numero": 1,
                    "pergunta": "Usar token Bearer ou cookie?",
                    "recomendacao": "Bearer",
                    "alternativas": ["cookie"],
                },
                {
                    "numero": 2,
                    "pergunta": "Publicar a API agora?",
                    "recomendacao": "nao, apos revisao",
                    "alternativas": [],
                },
            ]
            r = self._res("bloqueada", "Aguardando 2 decisao(oes) do desenvolvedor (simulado).", t0)
            r.pendencias.append("aguardando_decisoes_do_usuario")
            r.mensagens += [
                MensagemSaida(tipo="entendimento", conteudo="Voce quer definir a autenticacao da API (simulado)."),
                MensagemSaida(
                    tipo="decisoes",
                    conteudo="1. Usar token Bearer ou cookie?\n2. Publicar a API agora?",
                    dados={"decisoes": decisoes},
                ),
            ]
            return r
        r = self._res("concluida", "Conversa concluida apos as respostas (simulado).", t0)
        r.mensagens.append(
            MensagemSaida(
                tipo="resposta",
                conteudo=(
                    f"Considerei {len(retomada.get('respostas', []))} resposta(s) do desenvolvedor e segui com o plano (simulado)."
                ),
            )
        )
        r.artefatos.append(
            ArtefatoSaida(nome="relatorio.json", tipo="json", conteudo='{"simulado": true, "conversa": true}')
        )
        r.evidencias.append(
            EvidenciaSaida(
                tipo="mock_simulacao",
                resumo="Conversa simulada concluida; evidencia SIMULADA.",
                simulada=True,
                artefato="relatorio.json",
            )
        )
        return r

    def _escrita(self, tarefa: dict[str, Any], t0: float) -> ResultadoAgente:
        """Demonstra 'desfazer': cria UM arquivo sintetico identificado na 1a pasta de trabalho do projeto (nada mais)."""
        pastas = [p for p in ((tarefa.get("projeto_ctx") or {}).get("pastas") or []) if p.get("papel") == "trabalho"]
        if not pastas:
            return self._res("falhou", "Cenario 'escrita' exige uma pasta de trabalho no projeto (simulado).", t0)
        from pathlib import Path

        alvo = Path(pastas[0]["caminho"]) / f"forja-mock-{tarefa['id']}.txt"
        alvo.write_text("Arquivo SIMULADO criado pelo agente mock da Forja (pode ser desfeito).\n", encoding="utf-8")
        r = self._res("concluida", f"Arquivo simulado criado: {alvo.name}.", t0)
        r.evidencias.append(EvidenciaSaida(tipo="mock_simulacao", resumo=f"Criou {alvo.name} (SIMULADO).", simulada=True))
        return r

    def _coordenacao(self, info: dict[str, Any], t0: float) -> ResultadoAgente:
        """Master/sub-master SIMULADO: cria UMA tarefa de analise com o pedido (ou consolida sem criar nada)."""
        prompt = str(info.get("prompt") or "")
        if info.get("turno") == "consolidar":
            texto = "## Resposta\nLote concluído (simulado): todas as tarefas pararam. Nada mais a criar.\n## Ações\n```json\n{\"acoes\": []}\n```\n"
        else:
            pedido = prompt.rsplit("Pedido do usuario:", 1)[-1].strip().splitlines()[0][:100] if "Pedido do usuario:" in prompt else "pedido"
            projeto = "demo"
            if "projeto " in pedido.casefold():  # 'projeto X' no pedido escolhe o projeto (para testes)
                projeto = pedido.casefold().split("projeto ", 1)[1].split()[0].strip(".,;:")
            acoes: list[dict[str, Any]] = [{"tipo": "criar_tarefa", "projeto": projeto, "titulo": f"Analisar: {pedido}"[:120],
                                            "descricao": pedido, "modo": "analise", "criterios": ["resumo do que foi analisado"]}]
            if "projetos " in pedido.casefold() and "Voce e o MASTER" in prompt:  # 'projetos A e B': um sub-master por projeto
                nomes = [n.strip(".,;: ") for n in pedido.casefold().split("projetos ", 1)[1].replace(" e ", ",").split(",")]
                acoes = [{"tipo": "criar_submaster", "projeto": n, "objetivo": f"{pedido} (parte do projeto {n})"} for n in nomes if n][:3]
            texto = (f"## Resposta\nEntendi (simulado): {pedido}. Criei {len(acoes)} ação(ões).\n## Ações\n```json\n"
                     + json.dumps({"acoes": acoes}, ensure_ascii=False) + "\n```\n")
        r = self._res("concluida", "Turno de coordenacao simulado.", t0)
        r.artefatos.append(ArtefatoSaida(nome="resposta_coordenacao.md", tipo="texto", conteudo=texto))
        r.evidencias.append(EvidenciaSaida(tipo="mock_simulacao", resumo="Coordenacao SIMULADA.", simulada=True,
                                           artefato="resposta_coordenacao.md"))
        return r

    def _res(self, estado: str, resumo: str, t0: float) -> ResultadoAgente:
        return ResultadoAgente(
            estado=estado,  # type: ignore[arg-type]
            resumo=resumo,
            agente_id=self.id,
            mock=True,
            consumo=ConsumoMedicao(latencia_ms=int((time.monotonic() - t0) * 1000), fonte="simulado"),
        )
