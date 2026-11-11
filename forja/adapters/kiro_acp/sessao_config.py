"""Aplica modelo e esforco numa sessao ACP v3 (`session/set_config_option`).

Verificado com o kiro-cli 3.1.0 real: o engine v3 recusa `--model`/`--effort` na linha de comando; a escolha e feita por
sessao. O agente ACEITA em silencio um modelo inexistente (e some com as opcoes de esforco), entao o modelo e validado
contra a lista da propria sessao antes de aplicar e, se nao estiver nela, a execucao e BLOQUEADA (falha fechada):
melhor nao rodar do que rodar num modelo diferente do escolhido (custo e qualidade imprevisiveis).
"""

from __future__ import annotations

from typing import Any, Protocol


class ConfiguracaoIndisponivel(Exception):
    """O modelo pedido nao esta entre os modelos que a sessao oferece."""


class _Cliente(Protocol):
    opcoes_sessao: list[dict[str, Any]]

    def definir_opcao(self, session_id: str, config_id: str, valor: str, timeout: float = 20.0) -> list[dict[str, Any]]: ...


def valores(opcoes: list[dict[str, Any]], config_id: str) -> list[str]:
    for o in opcoes:
        if o.get("id") == config_id:
            return [str(v.get("value")) for v in o.get("options", []) if isinstance(v, dict)]
    return []


def aplicar_configuracao(cliente: _Cliente, session_id: str, modelo: str, esforco: str, timeout: float = 20.0,
                         alternativas: list[str] | None = None) -> dict[str, Any]:
    """`alternativas`: fallback EXPLICITO e ordenado escolhido pelo usuario. Usado so se o modelo principal faltar na conta;
    o resultado diz qual foi usado (`modelo_alternativo`). Sem alternativas validas, falha fechada como antes."""
    aplicados: dict[str, str] = {}
    avisos: list[str] = []
    if modelo:
        oferecidos = valores(cliente.opcoes_sessao, "model")
        escolhido = modelo if modelo in oferecidos else next((a for a in (alternativas or []) if a in oferecidos), None)
        if escolhido is None:
            raise ConfiguracaoIndisponivel(f"modelo {modelo!r} nao esta entre os modelos oferecidos pela sessao"
                                           + (" (nem as alternativas)" if alternativas else ""))
        if escolhido != modelo:
            avisos.append(f"modelo {modelo!r} indisponivel; usado o alternativo {escolhido!r} (configurado por voce)")
            aplicados["modelo_alternativo"] = escolhido
        cliente.definir_opcao(session_id, "model", escolhido, timeout)
        aplicados["modelo"] = escolhido
    if esforco:  # as opcoes de esforco dependem do modelo escolhido: so existem depois de aplica-lo
        if esforco in valores(cliente.opcoes_sessao, "effortLevel"):
            cliente.definir_opcao(session_id, "effortLevel", esforco, timeout)
            aplicados["esforco"] = esforco
        else:
            avisos.append("esforco indisponivel para este modelo; mantido o padrao do agente")
    return {"aplicados": aplicados, "avisos": avisos}
