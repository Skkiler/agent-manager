"""Organizacao automatica do segundo cerebro (sem IA, local) + fila de revisao.

Procura, em segundo plano ou sob demanda:
- DUPLICATAS: notas do mesmo namespace com o mesmo conteudo, ou titulo e texto muito parecidos (Jaccard de termos);
- DESATUALIZADAS: origem mudou (necessita revalidacao), validade vencida, contestadas paradas ha mais de 30 dias,
  candidatas esquecidas (mais de 90 dias, nunca usadas);
- LIGACOES: notas que compartilham 2+ tags e ainda nao estao ligadas.
Cada achado vira uma SUGESTAO pendente (deduplicada). Nada muda sem o usuario aceitar; aceitar usa os caminhos normais e
auditaveis da memoria (resolver conflito -> 'substituido', transicao -> 'obsoleto'/'revogado', ligacao tipada RELACIONADO_A).
A base curada da Forja (publico/forja-base) e somente leitura e fica de fora.
"""

from __future__ import annotations

import logging
import re
import threading
import unicodedata
from datetime import timedelta
from itertools import combinations
from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite, novo_id
from forja.dominio.erros import Conflito, NaoEncontrado, ValidacaoDominio
from forja.dominio.tempo import Relogio, RelogioSistema, iso
from forja.memoria.contratos import ResolverConflitoIn, TransicaoMemoriaIn
from forja.memoria.modelo import INATIVOS, EstadoMemoria, Principal, eh_base

log = logging.getLogger("forja.organizacao")
EM = EstadoMemoria
LIMIAR_TEXTO = 0.75
LIMIAR_TITULO = 0.5
MAX_POR_NAMESPACE = 3000
MAX_LIGACOES_POR_RODADA = 50
INTERVALO_S = 30 * 60
_RANK = {"validado": 5, "verificado": 4, "observado": 3, "candidato": 2, "contestado": 1}
_PALAVRA = re.compile(r"[a-z0-9_]{3,}")
_VAZIAS = frozenset("que para com uma por dos das nos nas como mais sem sobre entre quando onde este esta isso essa the and for with".split())


def termos(texto: str) -> set[str]:
    sem = "".join(c for c in unicodedata.normalize("NFKD", (texto or "").casefold()) if not unicodedata.combining(c))
    return {p for p in _PALAVRA.findall(sem) if p not in _VAZIAS}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


class OrganizadorMemoria:
    def __init__(self, repo: RepositorioSqlite, memoria: Any, grafo: Any, principal: Principal, relogio: Relogio | None = None) -> None:
        self.repo = repo
        self.memoria = memoria  # ServicoMemoria
        self.grafo = grafo  # GrafoServico (ligacoes tipadas)
        self.principal = principal
        self.relogio = relogio or RelogioSistema()
        self.modo = "sugerir"  # desligada | sugerir (preferencia 'organizacao_memoria')
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._mu = threading.Lock()

    # ------------------------------------------------------------------ deteccao
    def organizar(self) -> dict[str, Any]:
        """Uma rodada completa. Devolve quantas sugestoes NOVAS foram criadas, por tipo."""
        with self._mu:  # uma rodada por vez (botao + thread)
            agora = self.relogio.agora()
            with self.repo.leitura() as t:
                ativas = [m for m in t.listar(T.Memoria, limite=100_000)
                          if m["estado"] not in {e.value for e in INATIVOS} and not eh_base(m["namespace"]) and self.principal.pode(m["namespace"])]
                ligadas = {(x["origem"], x["destino"]) for x in t.listar(T.LigacaoGrafo, limite=100_000)}
                existentes = {s["chave"] for s in t.listar(T.SugestaoMemoria, limite=100_000)}
            novas: list[dict[str, Any]] = []
            por_ns: dict[str, list[dict]] = {}
            for m in ativas:
                por_ns.setdefault(m["namespace"], []).append(m)
            for ns, lista in por_ns.items():
                lista = sorted(lista, key=lambda m: m["atualizado_em"], reverse=True)[:MAX_POR_NAMESPACE]
                novas += self._duplicatas(ns, lista)
                novas += self._ligacoes(ns, lista, ligadas)
            novas += self._desatualizadas(ativas, agora)
            criadas: dict[str, int] = {}
            with self.repo.escrita() as t:
                for s in novas:
                    if s["chave"] in existentes:
                        continue
                    existentes.add(s["chave"])
                    t.inserir(T.SugestaoMemoria, id=novo_id("SUG"), estado="pendente", criado_em=iso(agora), **s)
                    criadas[s["tipo"]] = criadas.get(s["tipo"], 0) + 1
                t.emitir_evento("memoria.organizada", iso(agora), {"analisadas": len(ativas), "novas": criadas})
            return {"analisadas": len(ativas), "novas": criadas, "total_novas": sum(criadas.values())}

    @staticmethod
    def _chave(tipo: str, ids: list[str]) -> str:
        return f"{tipo}:{','.join(sorted(ids))}"[:200]

    def _duplicatas(self, ns: str, lista: list[dict]) -> list[dict[str, Any]]:
        saida: list[dict[str, Any]] = []
        vistos: set[str] = set()
        por_hash: dict[str, list[dict]] = {}
        for m in lista:
            por_hash.setdefault(m["hash_conteudo"], []).append(m)
        grupos = [g for g in por_hash.values() if len(g) > 1]
        # quase iguais: so compara pares que dividem um termo do TITULO (indice invertido evita O(n^2) cego)
        tt = {m["id"]: termos(m["titulo"]) for m in lista}
        tx = {m["id"]: termos(f"{m['titulo']} {m['resumo']} {(m['conteudo'] or '')[:3000]}") for m in lista}
        indice: dict[str, list[str]] = {}
        for m in lista:
            for termo in tt[m["id"]]:
                indice.setdefault(termo, []).append(m["id"])
        por_id = {m["id"]: m for m in lista}
        pares: set[tuple[str, str]] = set()
        for ids in indice.values():
            if len(ids) > 200:  # termo generico demais para indicar duplicata
                continue
            pares.update(tuple(sorted(p)) for p in combinations(ids, 2))  # type: ignore[misc]
        for a, b in sorted(pares):
            if por_id[a]["hash_conteudo"] == por_id[b]["hash_conteudo"]:
                continue
            if jaccard(tt[a], tt[b]) >= LIMIAR_TITULO and jaccard(tx[a], tx[b]) >= LIMIAR_TEXTO:
                grupos.append([por_id[a], por_id[b]])
        for g in grupos:
            ids = sorted({m["id"] for m in g})
            if len(ids) < 2 or tuple(ids) in vistos:
                continue
            vistos.add(tuple(ids))  # type: ignore[arg-type]
            venc = max(g, key=lambda m: (_RANK.get(m["estado"], 0), m.get("usos") or 0, m["atualizado_em"]))
            igual = len({m["hash_conteudo"] for m in g}) == 1
            saida.append({"tipo": "duplicata", "chave": self._chave("duplicata", ids), "memorias": ids, "namespace": ns,
                          "motivo": ("Mesmo conteudo" if igual else "Titulo e texto muito parecidos") + f" em {len(ids)} notas.",
                          "dados": {"vencedora_sugerida": venc["id"], "titulos": {m["id"]: m["titulo"][:120] for m in g}}})
        return saida

    def _desatualizadas(self, ativas: list[dict], agora: Any) -> list[dict[str, Any]]:
        saida = []
        limite_contestada = iso(agora - timedelta(days=30))
        limite_candidata = iso(agora - timedelta(days=90))
        for m in ativas:
            motivo = ""
            if m["necessita_revalidacao"]:
                motivo = "A origem mudou depois que a nota foi escrita (precisa revalidar)."
            elif m["validade_fim"] and m["validade_fim"] < iso(agora):
                motivo = "A validade declarada da nota venceu."
            elif m["estado"] == EM.CONTESTADO.value and m["atualizado_em"] < limite_contestada:
                motivo = "Contestada ha mais de 30 dias sem resolucao."
            elif m["estado"] == EM.CANDIDATO.value and m["atualizado_em"] < limite_candidata and not (m.get("usos") or 0):
                motivo = "Candidata ha mais de 90 dias e nunca usada por uma tarefa."
            if motivo:
                destino = "revogado" if m["estado"] == EM.CANDIDATO.value else "obsoleto"
                saida.append({"tipo": "desatualizada", "chave": self._chave(f"desatualizada:{m['versao']}", [m["id"]]), "memorias": [m["id"]],
                              "namespace": m["namespace"], "motivo": motivo,
                              "dados": {"destino": destino, "titulos": {m["id"]: m["titulo"][:120]}}})
        return saida

    def _ligacoes(self, ns: str, lista: list[dict], ligadas: set[tuple[str, str]]) -> list[dict[str, Any]]:
        saida: list[dict[str, Any]] = []
        por_tag: dict[str, list[dict]] = {}
        for m in lista:
            for tag in {str(x).casefold() for x in (m["tags"] or [])}:
                por_tag.setdefault(tag, []).append(m)
        comuns: dict[tuple[str, str], set[str]] = {}
        for tag, ms in por_tag.items():
            if len(ms) > 50:  # tag generica demais
                continue
            for a, b in combinations(sorted(ms, key=lambda m: m["id"]), 2):
                comuns.setdefault((a["id"], b["id"]), set()).add(tag)
        titulos = {m["id"]: m["titulo"][:120] for m in lista}
        for (a, b), tags in sorted(comuns.items(), key=lambda kv: -len(kv[1])):
            if len(tags) < 2 or (a, b) in ligadas or (b, a) in ligadas:
                continue
            saida.append({"tipo": "ligacao", "chave": self._chave("ligacao", [a, b]), "memorias": [a, b], "namespace": ns,
                          "motivo": f"Compartilham as tags {', '.join(sorted(tags)[:5])} e nao estao ligadas.",
                          "dados": {"tipo_ligacao": "RELACIONADO_A", "titulos": {a: titulos[a], b: titulos[b]}}})
            if len(saida) >= MAX_LIGACOES_POR_RODADA:
                break
        return saida

    # ------------------------------------------------------------------ fila de revisao
    def fila(self, p: Principal, limite: int = 100) -> dict[str, Any]:
        with self.repo.leitura() as t:
            candidatas = [m for m in t.listar(T.Memoria, estado=EM.CANDIDATO.value, limite=5000)
                          if p.pode(m["namespace"]) and not eh_base(m["namespace"])]
            sugestoes = [s for s in t.listar(T.SugestaoMemoria, estado="pendente", limite=5000) if p.pode(s["namespace"])]
            estados = {m["id"]: m["estado"] for m in t.listar(T.Memoria, limite=100_000)} if sugestoes else {}
        validas, obsoletas = [], []
        inativos = {e.value for e in INATIVOS}
        for s in sugestoes:  # notas que ja mudaram de estado (ou sumiram) invalidam a sugestao
            (obsoletas if any(estados.get(i) in inativos or i not in estados for i in s["memorias"]) else validas).append(s)
        if obsoletas:
            with self.repo.escrita() as t:
                for s in obsoletas:
                    t.atualizar(T.SugestaoMemoria, s["id"], estado="obsoleta", decidido_em=iso(self.relogio.agora()), decidido_por="sistema")
        candidatas.sort(key=lambda m: m["criado_em"], reverse=True)
        return {"candidatas": [{"id": m["id"], "titulo": m["titulo"], "resumo": m["resumo"][:300], "namespace": m["namespace"], "versao": m["versao"],
                                "tipo": m["tipo"], "tags": m["tags"], "criado_em": m["criado_em"], "usos": m.get("usos") or 0,
                                "suspeita_injecao": bool((m["sinalizadores"] or {}).get("suspeita_injecao"))} for m in candidatas[:limite]],
                "sugestoes": [{k: s[k] for k in ("id", "tipo", "memorias", "namespace", "motivo", "dados", "criado_em")} for s in validas[:limite]],
                "total": len(candidatas) + len(validas), "modo": self.modo}

    def decidir(self, p: Principal, sugestao_id: str, aceitar: bool, ator: str = "operador", vencedora_id: str | None = None) -> dict[str, Any]:
        with self.repo.leitura() as t:
            s = t.obter(T.SugestaoMemoria, sugestao_id)
        if s is None or not p.pode(s["namespace"]):
            raise NaoEncontrado(f"Sugestao {sugestao_id} nao encontrada.")
        if s["estado"] != "pendente":
            raise Conflito(f"Sugestao ja decidida ({s['estado']}).")
        resultado: dict[str, Any] = {}
        if aceitar:
            resultado = self._aplicar(p, s, ator, vencedora_id)
        agora = iso(self.relogio.agora())
        with self.repo.escrita() as t:
            t.atualizar(T.SugestaoMemoria, sugestao_id, estado="aceita" if aceitar else "rejeitada", decidido_em=agora, decidido_por=ator[:100])
            t.emitir_evento("memoria.sugestao_decidida", agora, {"sugestao_id": sugestao_id, "tipo": s["tipo"], "aceita": aceitar})
        return {"id": sugestao_id, "estado": "aceita" if aceitar else "rejeitada", "resultado": resultado}

    def _aplicar(self, p: Principal, s: dict[str, Any], ator: str, vencedora_id: str | None) -> dict[str, Any]:
        dados = s["dados"] or {}
        if s["tipo"] == "duplicata":
            venc = vencedora_id or dados.get("vencedora_sugerida")
            if venc not in s["memorias"]:
                raise ValidacaoDominio("A nota que fica deve ser uma das duplicadas.")
            return self.memoria.resolver_conflito(p, ResolverConflitoIn(
                vencedora_id=venc, perdedoras_ids=[i for i in s["memorias"] if i != venc], motivo=f"duplicata: {s['motivo']}"[:1000]), ator)
        if s["tipo"] == "desatualizada":
            mid = s["memorias"][0]
            m = self.memoria.obter(p, mid)
            return self.memoria.transicionar(p, mid, TransicaoMemoriaIn(para=EM(dados.get("destino", "obsoleto")), expected_version=m["versao"],
                                                                        motivo=f"organizacao: {s['motivo']}"[:1000]), ator)
        if s["tipo"] == "ligacao":
            a, b = s["memorias"][:2]
            return self.grafo.ligar(p, a, b, dados.get("tipo_ligacao", "RELACIONADO_A"), "sugerida pela organizacao automatica", ator)
        raise ValidacaoDominio(f"tipo de sugestao desconhecido: {s['tipo']}")

    # ------------------------------------------------------------------ segundo plano
    def iniciar(self, atraso_s: float = 60.0, intervalo_s: float = INTERVALO_S) -> None:
        if self._thread is not None:
            return

        def laco() -> None:
            if self._parar.wait(atraso_s):
                return
            while not self._parar.is_set():
                if self.modo == "sugerir":
                    try:
                        self.organizar()
                    except Exception as e:  # noqa: BLE001 - organizar e manutencao; tenta de novo no proximo ciclo
                        log.warning("organizacao do segundo cerebro falhou: %s", type(e).__name__)
                if self._parar.wait(intervalo_s):
                    return

        self._thread = threading.Thread(target=laco, daemon=True, name="forja-organizacao")
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()
