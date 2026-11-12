"""Grafo do segundo cerebro para visualizacao (estilo Obsidian): memorias, nos tipados, [[wikilinks]], refs e backlinks.

Respeita a ACL de namespaces ANTES de montar qualquer no. Edicao: ligacoes tipadas criadas/removidas pela tela (4.22), com a
mesma ontologia das arestas de conhecimento; o conteudo das notas continua sendo editado pelas rotas de memoria.
"""

from __future__ import annotations

from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite, novo_id
from forja.dominio.erros import Conflito, NaoEncontrado, ValidacaoDominio
from forja.dominio.tempo import RelogioSistema, iso
from forja.memoria.modelo import ARESTAS, Principal, eh_base, namespace_dentro_de
from forja.memoria.wikilinks import extrair_wikilinks

INATIVOS = frozenset({"revogado", "substituido"})


def _dentro(ns: str, alvo: set[str]) -> bool:
    return any(namespace_dentro_de(ns, a) for a in alvo)  # mesma regra de prefixo da ACL (publico inclui publico/x)
MAX_NOS = 500
MAX_FANTASMAS = 40


class GrafoServico:
    def __init__(self, repo: RepositorioSqlite, relogio: Any | None = None) -> None:
        self.repo = repo
        self.relogio = relogio or RelogioSistema()

    # ------------------------------------------------------------------ carga com ACL
    def _carregar(self, p: Principal, namespaces: list[str], incluir_inativas: bool, incluir_base: bool = True):
        alvo = set(p.filtrar(namespaces))
        with self.repo.leitura() as t:
            memorias = [m for m in t.listar(T.Memoria, limite=5000) if _dentro(m["namespace"], alvo)
                        and (incluir_inativas or m["estado"] not in INATIVOS)]
            nos = [n for n in t.listar(T.NoConhecimento, limite=5000) if _dentro(n["namespace"], alvo)]
            arestas = [a for a in t.listar(T.ArestaConhecimento, limite=10000) if _dentro(a["namespace"], alvo)]
            arestas += [{**lg, "editavel": not eh_base(lg["namespace"])} for lg in t.listar(T.LigacaoGrafo, limite=10000) if _dentro(lg["namespace"], alvo)]
        if not incluir_base:  # a base da Forja (60+ notas) fica fora da vista por padrao; continua na busca e no contexto
            memorias = [m for m in memorias if not eh_base(m["namespace"])]
            arestas = [a for a in arestas if not eh_base(a.get("namespace", ""))]
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
              incluir_inativas: bool = False, incluir_base: bool = False) -> dict[str, Any]:
        memorias, nos, arestas_k = self._carregar(p, namespaces, incluir_inativas, incluir_base)
        arestas, fantasmas = self._arestas_de_memorias(memorias)
        arestas += [{"origem": a["origem"], "destino": a["destino"], "tipo": a["tipo"],
                     **({"id": a["id"], "editavel": True, "nota": a.get("nota", "")} if a.get("editavel") else {})} for a in arestas_k]
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

    # ------------------------------------------------------------------ edicao (4.22)
    def _ponta(self, t: Any, p: Principal, id_: str) -> dict[str, Any]:
        item = t.obter(T.Memoria, id_) or t.obter(T.NoConhecimento, id_)
        if item is None or not p.pode(item["namespace"]):
            raise NaoEncontrado(f"Item {id_} nao encontrado.")  # sem oraculo de existencia fora da ACL
        return item

    def ligar(self, p: Principal, origem: str, destino: str, tipo: str, nota: str = "", ator: str = "operador") -> dict[str, Any]:
        if tipo not in ARESTAS:
            raise ValidacaoDominio(f"tipo de ligacao fora da ontologia: {tipo!r}")
        if origem == destino:
            raise ValidacaoDominio("Uma ligacao nao pode ligar um item a si mesmo.")
        agora = iso(self.relogio.agora())
        with self.repo.escrita() as t:
            a, b = self._ponta(t, p, origem), self._ponta(t, p, destino)
            ns = b["namespace"] if a["namespace"] == "publico" else a["namespace"]  # fica no escopo mais privado das pontas
            if t.listar(T.LigacaoGrafo, origem=origem, destino=destino, tipo=tipo, limite=1):
                raise Conflito("Essa ligacao ja existe.")
            lg = t.inserir(T.LigacaoGrafo, id=novo_id("LIG"), origem=origem, destino=destino, tipo=tipo, namespace=ns,
                           nota=(nota or "").strip()[:300], criado_por=ator[:100], criado_em=agora)
            t.emitir_evento("memoria.ligacao_criada", agora, {"id": lg["id"], "tipo": tipo})
        return lg

    def desligar(self, p: Principal, ligacao_id: str) -> None:
        agora = iso(self.relogio.agora())
        with self.repo.escrita() as t:
            lg = t.obter(T.LigacaoGrafo, ligacao_id)
            if lg is None or not p.pode(lg["namespace"]):
                raise NaoEncontrado(f"Ligacao {ligacao_id} nao encontrada.")
            t.s.delete(t.s.get(T.LigacaoGrafo, ligacao_id))
            t.emitir_evento("memoria.ligacao_removida", agora, {"id": ligacao_id})

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
