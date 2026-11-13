"""Visoes de leitura para a interface: quadro Kanban de tarefas. Somente leitura; as acoes usam a API existente."""

from __future__ import annotations

from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.dominio.estados import EstadoTarefa as E
from forja.dominio.estados import eh_terminal
from forja.dominio.tempo import Relogio, RelogioSistema, iso

# (id, rotulo, estados). Todo estado de tarefa pertence a exatamente uma coluna (verificado em teste).
COLUNAS: tuple[tuple[str, str, tuple[E, ...]], ...] = (
    ("backlog", "Backlog", (E.RASCUNHO, E.CLASSIFICADA, E.PREPARADA, E.AGUARDANDO_DEPENDENCIAS)),
    ("pronta", "Pronta", (E.PRONTA, E.ATRIBUIDA)),
    ("executando", "Em execucao", (E.EXECUTANDO, E.VALIDANDO)),
    ("atencao", "Precisa de voce", (E.BLOQUEADA, E.AGUARDANDO_APROVACAO)),
    ("concluida", "Concluida", (E.CONCLUIDA,)),
    ("encerradas", "Falhou / cancelada", (E.FALHOU, E.CANCELADA, E.EXPIRADA)),
)
LIMITE_POR_COLUNA = 50
PRECISA_DE_VOCE = frozenset({E.BLOQUEADA.value, E.AGUARDANDO_APROVACAO.value})
_EM_CURSO = frozenset({E.ATRIBUIDA.value, E.EXECUTANDO.value, E.VALIDANDO.value, E.AGUARDANDO_APROVACAO.value})


def acoes_do_cartao(estado: str) -> list[dict[str, str]]:
    """Acoes que fazem sentido no estado, mapeadas para chamadas da API (a UI nunca inventa transicao)."""
    e = E(estado)
    acoes: list[dict[str, str]] = []
    if e in (E.RASCUNHO, E.CLASSIFICADA):
        acoes.append({"id": "preparar", "rotulo": "Preparar"})
    if e == E.PRONTA:
        acoes.append({"id": "executar", "rotulo": "Executar"})
    if e == E.BLOQUEADA:
        acoes.append({"id": "conversa", "rotulo": "Responder"})
    if e == E.AGUARDANDO_APROVACAO:
        acoes.append({"id": "aprovacoes", "rotulo": "Ver aprovacoes"})
    if e != E.BLOQUEADA:
        acoes.append({"id": "conversa", "rotulo": "Conversa"})
    if not eh_terminal(e):
        acoes.append({"id": "cancelar", "rotulo": "Cancelar"})
    return acoes


class VisaoKanban:
    def __init__(self, repo: RepositorioSqlite, relogio: Relogio | None = None) -> None:
        self.repo = repo
        self.relogio = relogio or RelogioSistema()
        self.restauracao: Any | None = None  # PontosRestauracao: tarefas com alteracoes que podem ser desfeitas

    def montar(self, projeto_id: str | None = None, objetivo_id: str | None = None) -> dict[str, Any]:
        filtros = {k: v for k, v in (("projeto_id", projeto_id), ("objetivo_id", objetivo_id)) if v}
        with self.repo.leitura() as t:
            tarefas = t.listar(T.Tarefa, limite=5000, **filtros)
            prioridade = {o["id"]: o["prioridade"] for o in t.listar(T.Objetivo, limite=5000)}
        por_estado: dict[str, list[dict]] = {}
        for tf in tarefas:
            por_estado.setdefault(tf["estado"], []).append(tf)
        try:  # cartoes com alteracoes reversiveis ganham 'Desfazer alteracoes' (so tarefas paradas: nada escreve agora)
            parados = [tf["id"] for tf in tarefas if tf["estado"] not in _EM_CURSO]
            desfazer = self.restauracao.tem_desfazer(parados) if self.restauracao is not None else set()
        except Exception:  # noqa: BLE001 - o botao e conveniencia; o quadro nunca falha por ele
            desfazer = set()
        colunas = []
        for cid, rotulo, estados in COLUNAS:
            itens = [tf for e in estados for tf in por_estado.get(e.value, [])]
            itens.sort(key=lambda x: (prioridade.get(x["objetivo_id"], 3), _inverso(x["atualizado_em"])))
            cartoes = [self._cartao(tf, prioridade) for tf in itens[:LIMITE_POR_COLUNA]]
            for c in cartoes:
                if c["id"] in desfazer:
                    c["acoes"].append({"id": "desfazer", "rotulo": "Desfazer alterações"})
            colunas.append({
                "id": cid, "rotulo": rotulo, "estados": [e.value for e in estados], "total": len(itens), "cartoes": cartoes,
            })
        return {"gerado_em": iso(self.relogio.agora()), "total": len(tarefas), "colunas": colunas,
                "precisa_de_voce": sum(len(por_estado.get(s, [])) for s in PRECISA_DE_VOCE)}

    @staticmethod
    def _cartao(tf: dict, prioridade: dict[str, int]) -> dict[str, Any]:
        return {
            "id": tf["id"], "titulo": tf["titulo"], "estado": tf["estado"], "versao_estado": tf["versao_estado"],
            "projeto_id": tf["projeto_id"], "objetivo_id": tf["objetivo_id"],
            "prioridade": prioridade.get(tf["objetivo_id"], 3), "tentativas": tf["tentativas"],
            "especialidade": tf["especialidade"], "modo": tf["modo"], "dependencias": len(tf["dependencias"] or []),
            "motivo": (tf["motivo_estado"] or "")[:160], "atualizado_em": tf["atualizado_em"],
            "precisa_de_voce": tf["estado"] in PRECISA_DE_VOCE, "acoes": acoes_do_cartao(tf["estado"]),
        }


def _inverso(iso_txt: str) -> tuple[int, ...]:
    """Chave para ordenar texto ISO do mais recente para o mais antigo sem inverter a lista inteira."""
    return tuple(-ord(c) for c in iso_txt)
