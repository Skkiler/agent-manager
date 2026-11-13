"""Controle de escopo (anti 'esticar'): confere de forma deterministica se o agente fez MAIS do que a tarefa pediu.

Causa medida no mercado: o system prompt do kiro-cli manda agir sem hesitar e o prompt do agente perde em conflito
(kirodotdev/Kiro#7792); o fluxo de specs puxa documentacao extra (#3474). A Forja nao confia so na instrucao:
- durante a execucao, passar do limite de arquivos do nivel faz cada nova escrita PERGUNTAR (mediador);
- ao terminar, compara os arquivos alterados (medidos pelo ponto de restauracao) com o plano e o limite e, se sair do escopo,
  a tarefa fica 'bloqueada' (preferencia 'pausar') com a lista: voce desfaz com um clique ou responde para aceitar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

LIMITE_ARQUIVOS = {"simples": 3, "normal": 10, "complexa": 25}
MODOS = ("pausar", "avisar", "desligado")
_CAMINHO = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.[A-Za-z0-9]{1,8})(?![\w/])")
_DOCS = (".md", ".rst", ".adoc")
_PEDE_DOC = re.compile(r"(?i)\b(readme|documenta\w*|docs?\b|changelog|guia|manual|\.md\b|adr)")


def limite(nivel: str) -> int:
    return LIMITE_ARQUIVOS.get(nivel, LIMITE_ARQUIVOS["normal"])


def arquivos_do_plano(texto: str) -> set[str]:
    return {m.group(1).strip("./").casefold() for m in _CAMINHO.finditer(texto or "") if not m.group(1).startswith("http")}


def _no_plano(caminho: str, plano: set[str]) -> bool:
    c = caminho.casefold()
    nome = PurePosixPath(c).name
    return any(c == p or c.endswith("/" + p) or p.endswith("/" + c) or PurePosixPath(p).name == nome for p in plano)


@dataclass
class Avaliacao:
    alterados: list[str]
    limite: int
    motivos: list[str] = field(default_factory=list)
    fora_do_plano: list[str] = field(default_factory=list)
    docs_nao_pedidos: list[str] = field(default_factory=list)

    @property
    def saiu(self) -> bool:
        return bool(self.motivos)


def avaliar(tarefa: dict[str, Any], nivel: str, resumos: list[dict[str, Any]], plano_texto: str) -> Avaliacao:
    alterados = sorted({x for r in resumos for k in ("alterados", "adicionados", "removidos") for x in (r.get(k) or [])})
    adicionados = {x for r in resumos for x in (r.get("adicionados") or [])}
    av = Avaliacao(alterados, limite(nivel))
    if len(alterados) > av.limite:
        av.motivos.append(f"{len(alterados)} arquivos alterados (limite do nivel '{nivel}': {av.limite})")
    pedido = f"{tarefa.get('titulo', '')} {tarefa.get('descricao') or ''} {' '.join(tarefa.get('criterios_aceite') or [])}"
    if tarefa.get("modo") != "documentacao" and not _PEDE_DOC.search(pedido):
        av.docs_nao_pedidos = sorted(a for a in adicionados if a.casefold().endswith(_DOCS))
        if av.docs_nao_pedidos:
            av.motivos.append(f"documentacao nao pedida: {', '.join(av.docs_nao_pedidos[:5])}")
    plano = arquivos_do_plano(plano_texto)
    if plano:
        av.fora_do_plano = [a for a in alterados if not _no_plano(a, plano)]
        if len(av.fora_do_plano) > max(2, len(alterados) * 0.3):
            av.motivos.append(f"{len(av.fora_do_plano)} arquivos fora do plano: {', '.join(av.fora_do_plano[:5])}")
    return av
