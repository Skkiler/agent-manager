"""Grafo do segundo cerebro para visualizacao (estilo Obsidian): memorias, nos tipados, [[wikilinks]], refs e backlinks.

Respeita a ACL de namespaces ANTES de montar qualquer no. So leitura; a edicao usa as rotas de memoria existentes.
"""

from __future__ import annotations

from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite
from forja.dominio.erros import NaoEncontrado
from forja.memoria.modelo import Principal
from forja.memoria.wikilinks import extrair_wikilinks

INATIVOS = frozenset({"revogado", "substituido"})
MAX_NOS = 500
MAX_FANTASMAS = 40


class GrafoServico:
    def __init__(self, repo: RepositorioSqlite) -> None:
        self.repo = repo

    # ------------------------------------------------------------------ carga com ACL
    def _carregar(self, p: Principal, namespaces: list[str], incluir_inativas: bool):
        alvo = set(p.filtrar(namespaces))
        with self.repo.leitura() as t:
            memorias = [m for m in t.listar(T.Memoria, limite=5000) if m["namespace"] in alvo
                        and (incluir_inativas or m["estado"] not in INATIVOS)]
            nos = [n for n in t.listar(T.NoConhecimento, limite=5000) if n["namespace"] in alvo]
            arestas = [a for a in t.listar(T.ArestaConhecimento, limite=10000) if a["namespace"] in alvo]
        return memorias, nos, arestas

    @staticmethod
    def _arestas_de_memorias(memorias: list[dict]) -> tuple[list[dict], dict[str, None]]:
        """Arestas wikilink/ref entre memorias + titulos citados que nao existem (links fantasmas, como no Obsidian)."""
        por_titulo: dict[str, str] = {}
        for m in memorias:
            por_titulo.setdefault(m["titulo"].casefold(), m["id"])
        ids = {m["id"] for m in memorias}
        arestas: list[dict] = []
        fantasmas: dict[str, None] = {}
        for m in memorias:
            for alvo in extrair_wikilinks(f"{m['resumo']}\n{m['conteudo']}"):
                destino = por_titulo.get(alvo.casefold())
                if destino and destino != m["id"]:
                    arestas.append({"origem": m["id"], "destino": destino, "tipo": "wikilink"})
                elif not destino:
                    fantasmas.setdefault(alvo, None)
                    arestas.append({"origem": m["id"], "destino": f"?{alvo}", "tipo": "wikilink"})
            for ref in m["refs"] or []:
                if ref.startswith("memoria:") and ref[8:] in ids and ref[8:] != m["id"]:
                    arestas.append({"origem": m["id"], "destino": ref[8:], "tipo": "ref"})
            if m.get("substituida_por") in ids:
                arestas.append({"origem": m["id"], "destino": m["substituida_por"], "tipo": "substituida_por"})
        return arestas, fantasmas

    # ------------------------------------------------------------------ visoes
    def grafo(self, p: Principal, namespaces: list[str], q: str = "", limite: int = 200, vizinhos: int = 1,
              incluir_inativas: bool = False) -> dict[str, Any]:
        memorias, nos, arestas_k = self._carregar(p, namespaces, incluir_inativas)
        arestas, fantasmas = self._arestas_de_memorias(memorias)
        arestas += [{"origem": a["origem"], "destino": a["destino"], "tipo": a["tipo"]} for a in arestas_k]
        todos: dict[str, dict] = {}
        for m in memorias:
            todos[m["id"]] = {"id": m["id"], "rotulo": m["titulo"], "grupo": "memoria", "tipo": m["tipo"],
                              "estado": m["estado"], "namespace": m["namespace"], "tags": m["tags"] or [],
                              "atualizado_em": m["atualizado_em"]}
        for n in nos:
            todos[n["id"]] = {"id": n["id"], "rotulo": n["nome"], "grupo": "no", "tipo": n["tipo"],
                              "estado": n["estado"], "namespace": n["namespace"], "tags": [],
                              "atualizado_em": n["criado_em"]}
        for titulo in list(fantasmas)[:MAX_FANTASMAS]:
            todos[f"?{titulo}"] = {"id": f"?{titulo}", "rotulo": titulo, "grupo": "fantasma", "tipo": "nao_resolvido",
                                   "estado": "", "namespace": "", "tags": [], "atualizado_em": ""}
        arestas = [a for a in arestas if a["origem"] in todos and a["destino"] in todos]

        escolhidos = self._selecionar(todos, memorias, arestas, q, vizinhos)
        grau: dict[str, int] = dict.fromkeys(escolhidos, 0)
        arestas = [a for a in arestas if a["origem"] in escolhidos and a["destino"] in escolhidos]
        for a in arestas:
            grau[a["origem"]] += 1
            grau[a["destino"]] += 1
        limite = min(limite, MAX_NOS)
        ordenados = sorted(escolhidos, key=lambda i: (-grau[i], _neg(todos[i]["atualizado_em"]), i))[:limite]
        mantidos = set(ordenados)
        saida_nos = [{**todos[i], "grau": grau[i]} for i in ordenados]
        saida_arestas = [a for a in arestas if a["origem"] in mantidos and a["destino"] in mantidos]
        return {"nos": saida_nos, "arestas": _unicas(saida_arestas), "truncado": len(escolhidos) > len(ordenados),
                "total_memorias": len(memorias), "total_nos": len(nos), "fantasmas": len(fantasmas)}

    @staticmethod
    def _selecionar(todos: dict[str, dict], memorias: list[dict], arestas: list[dict], q: str, vizinhos: int) -> set[str]:
        termos = [x for x in q.casefold().split() if x]
        if not termos:
            return set(todos)
        textos = {m["id"]: f"{m['titulo']} {m['resumo']} {m['conteudo']} {' '.join(m['tags'] or [])}".casefold()
                  for m in memorias}
        sementes = {i for i, tx in textos.items() if all(t in tx for t in termos)}
        sementes |= {i for i, n in todos.items() if n["grupo"] != "memoria" and all(t in n["rotulo"].casefold() for t in termos)}
        escolhidos = set(sementes)
        for _ in range(max(0, vizinhos)):
            novos = set()
            for a in arestas:
                if a["origem"] in escolhidos:
                    novos.add(a["destino"])
                if a["destino"] in escolhidos:
                    novos.add(a["origem"])
            escolhidos |= novos
        return escolhidos

    def links(self, p: Principal, memoria_id: str) -> dict[str, Any]:
        """Saida e entrada (backlinks) de uma memoria, no estilo do painel de backlinks do Obsidian."""
        with self.repo.leitura() as t:
            alvo = t.obter(T.Memoria, memoria_id)
        if alvo is None or not p.pode(alvo["namespace"]):
            raise NaoEncontrado(f"Memoria {memoria_id} nao encontrada.")  # sem oraculo de existencia (igual ao ServicoMemoria)
        memorias, _, _ = self._carregar(p, [alvo["namespace"]], incluir_inativas=True)
        arestas, _ = self._arestas_de_memorias(memorias)
        nomes = {m["id"]: m["titulo"] for m in memorias}
        saida = [{"id": a["destino"], "titulo": nomes.get(a["destino"], a["destino"][1:]), "tipo": a["tipo"],
                  "resolvido": not a["destino"].startswith("?")} for a in arestas if a["origem"] == memoria_id]
        entrada = [{"id": a["origem"], "titulo": nomes[a["origem"]], "tipo": a["tipo"]}
                   for a in arestas if a["destino"] == memoria_id and a["origem"] in nomes]
        return {"memoria_id": memoria_id, "saida": _unicas(saida, ("id", "tipo")),
                "entrada": _unicas(entrada, ("id", "tipo"))}


def _unicas(itens: list[dict], chaves: tuple[str, ...] = ("origem", "destino", "tipo")) -> list[dict]:
    vistos: set[tuple] = set()
    saida = []
    for i in itens:
        k = tuple(i[c] for c in chaves)
        if k not in vistos:
            vistos.add(k)
            saida.append(i)
    return saida


def _neg(txt: str) -> tuple[int, ...]:
    return tuple(-ord(c) for c in txt)
