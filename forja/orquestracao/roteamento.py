"""Roteamento adaptativo por complexidade (deterministico, sem LLM, custo zero).

Objetivo: tarefa SIMPLES sai rapido, barata e direta; tarefa COMPLEXA e planejada (e pesquisada) antes de executar, com
modelo mais forte e verificacao. A classificacao usa so sinais objetivos da tarefa; o usuario pode forcar o nivel com
`politicas.complexidade` (simples | normal | complexa).

| nivel    | parte do modelo        | turnos                         | contexto | correcao com testes |
|----------|------------------------|--------------------------------|----------|---------------------|
| simples  | rapida (haiku)         | 1                              | x0,5     | nao                 |
| normal   | execucao (sonnet)      | 1 (+1 se testes falharem)      | x1       | sim (codigo)        |
| complexa | planejamento -> execucao | plano + execucao (+1 correcao) | x1,5     | sim (codigo)        |
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

NIVEIS = ("simples", "normal", "complexa")
_COMPLEXOS = re.compile(
    r"\b(arquitetur\w*|refator\w*|migra\w*|redesenh\w*|reescrev\w*|concorren\w*|paralel\w*|seguranc\w*|autentica\w*|"
    r"autoriza\w*|desempenho|performance|escal\w*|integra\w*|distribu\w*|multipl\w*|varios|varias|todo o|todos os|"
    r"pipeline|infraestrutura|banco de dados|schema|esquema|criptograf\w*|planej\w*|pesquis\w*|investig\w*|"
    r"depura\w*|race|deadlock|vazamento|memory leak)\b")
_SIMPLES = re.compile(r"\b(explique|explicar|o que e|o que faz|resuma|resumir|liste|listar|renomei\w*|corrija o typo|typo|"
                      r"comentario|docstring|readme|qual|onde fica|como funciona)\b")


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s.casefold()) if not unicodedata.combining(c))


@dataclass(frozen=True)
class Rota:
    nivel: str
    parte: str  # parte da configuracao (modelo/esforco) usada na execucao
    planejar: bool  # turno de plano (parte 'planejamento') antes de executar
    fator_contexto: float
    corrigir: bool  # rodada unica de correcao com testes (se a tarefa altera codigo)
    motivos: tuple[str, ...] = field(default_factory=tuple)

    def como_dict(self) -> dict[str, Any]:
        return {"nivel": self.nivel, "parte": self.parte, "planejar": self.planejar, "fator_contexto": self.fator_contexto,
                "corrigir": self.corrigir, "motivos": list(self.motivos)}


def classificar(tarefa: dict[str, Any]) -> Rota:
    modo = tarefa.get("modo") or "analise"
    entrada = tarefa.get("entrada") or {}
    if entrada.get("revisao"):
        return Rota("complexa", "revisao", False, 1.0, False, ("revisao do esquema",))
    if modo == "estudo" or entrada.get("estudo"):
        return Rota("normal", "estudo", False, 0.5, False, ("estudo/alimentacao do segundo cerebro",))
    forcado = ((tarefa.get("politicas") or {}).get("complexidade") or "").strip()
    texto = _norm(f"{tarefa.get('titulo', '')} {tarefa.get('descricao') or ''}")
    criterios = tarefa.get("criterios_aceite") or []
    ctx = tarefa.get("projeto_ctx") or {}
    pastas, anexos = len(ctx.get("pastas") or []), len(ctx.get("anexos") or [])
    escreve = modo in ("alteracao_codigo", "verificacao")
    motivos: list[str] = []
    pontos = 0
    if len(texto) > 600:
        pontos += 2
        motivos.append("descricao longa")
    if len(criterios) >= 4:
        pontos += 2
        motivos.append(f"{len(criterios)} criterios de aceite")
    termos = sorted(set(_COMPLEXOS.findall(texto)))
    if termos:
        pontos += min(len(termos), 3)
        motivos.append("termos de complexidade: " + ", ".join(termos[:4]))
    if pastas >= 2:
        pontos += 1
        motivos.append(f"{pastas} pastas no projeto")
    if anexos >= 3:
        pontos += 1
        motivos.append(f"{anexos} anexos")
    if escreve:
        pontos += 1
    simples_por_texto = bool(_SIMPLES.search(texto)) and len(texto) < 280 and len(criterios) <= 2 and not termos
    if forcado in NIVEIS:
        nivel = forcado
        motivos = [f"definido na tarefa ({forcado})"]
    elif pontos >= 4:
        nivel = "complexa"
    elif not escreve and (simples_por_texto or (pontos == 0 and len(texto) < 200)):
        nivel = "simples"
        motivos.append("pergunta curta e somente leitura")
    else:
        nivel = "normal"
    if nivel == "simples":
        return Rota("simples", "rapida", False, 0.5, False, tuple(motivos))
    if nivel == "complexa":
        return Rota("complexa", "execucao", True, 1.5, escreve, tuple(motivos))
    return Rota("normal", "execucao", False, 1.0, escreve, tuple(motivos))
