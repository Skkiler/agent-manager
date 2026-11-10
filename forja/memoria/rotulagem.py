"""4.8: precisao da busca sobre o SEU corpus real, com rotulos dados por voce.

Por que existe: o benchmark publico e sintetico; so voce sabe quais resultados sao relevantes para as suas perguntas. Os rotulos
ficam no banco do seu perfil (fora do Git) e guardam apenas a consulta e os IDs marcados, nunca o conteudo das memorias.

Sem vies de rotulagem: os candidatos mostrados sao a UNIAO do baseline lexical com a busca nova, em ordem embaralhada de forma
deterministica, para que voce nao rotule so o que a busca atual ja acha.
"""

from __future__ import annotations

import hashlib
from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite, novo_id
from forja.dominio.erros import ConflitoVersao, NaoEncontrado, ValidacaoDominio
from forja.dominio.tempo import Relogio, RelogioSistema, iso
from forja.memoria.avaliacao import Caso, avaliar
from forja.memoria.modelo import Principal

CHAVE = "rotulos_busca"
MAX_CASOS = 300
MIN_CONFIAVEL = 15  # abaixo disso a media oscila demais para decidir algo (ex.: adotar embeddings)
CANDIDATOS = 10


class RotulagemServico:
    def __init__(self, repo: RepositorioSqlite, memoria: Any, relogio: Relogio | None = None) -> None:
        self.repo, self.memoria, self.relogio = repo, memoria, relogio or RelogioSistema()

    def _ler(self) -> tuple[list[dict[str, Any]], int]:
        with self.repo.leitura() as t:
            linha = t.obter(T.Configuracao, CHAVE)
        return list(((linha or {}).get("valor") or {}).get("casos") or []), (linha or {}).get("versao", 0)

    def _gravar(self, casos: list[dict[str, Any]], expected_version: int, evento: str, dados: dict[str, Any]) -> None:
        agora = iso(self.relogio.agora())
        with self.repo.escrita() as t:
            linha = t.obter(T.Configuracao, CHAVE)
            atual = linha["versao"] if linha else 0
            if expected_version != atual:
                raise ConflitoVersao(f"Os rotulos mudaram (versao {atual}); recarregue.")
            if linha is None:
                t.inserir(T.Configuracao, id=CHAVE, valor={"casos": casos}, versao=1, atualizado_em=agora)
            else:
                t.atualizar(T.Configuracao, CHAVE, valor={"casos": casos}, versao=atual + 1, atualizado_em=agora)
            t.emitir_evento(evento, agora, dados)  # so ids e contagens: a consulta pode ser pessoal

    def _ranking(self, p: Principal, consulta: str, namespaces: list[str], expandir: bool, limite: int = CANDIDATOS) -> list[dict[str, Any]]:
        try:
            r = self.memoria.buscar(p, consulta, namespaces, limite=limite, expandir=expandir)
        except ValidacaoDominio:
            return []  # consulta sem termos uteis conta como zero acertos (igual ao benchmark)
        return list(r.get("resultados") or [])

    def _namespaces(self, p: Principal, namespaces: list[str] | None) -> list[str]:
        ns = namespaces or sorted(p.namespaces)
        fora = [n for n in ns if n not in p.namespaces]
        if fora:
            raise ValidacaoDominio(f"namespaces nao permitidos para voce: {', '.join(fora)}")
        return ns

    # ------------------------------------------------------------------ rotular
    def candidatos(self, p: Principal, consulta: str, namespaces: list[str] | None = None) -> dict[str, Any]:
        consulta = (consulta or "").strip()
        if not 2 <= len(consulta) <= 300:
            raise ValidacaoDominio("escreva uma pergunta de 2 a 300 caracteres")
        ns = self._namespaces(p, namespaces)
        vistos: dict[str, dict[str, Any]] = {}
        for expandir in (False, True):
            for item in self._ranking(p, consulta, ns, expandir):
                vistos.setdefault(item["id"], {k: item.get(k) for k in ("id", "titulo", "fonte", "tipo", "namespace", "trecho", "resumo", "caminho")
                                               if item.get(k) is not None})
        ordem = sorted(vistos, key=lambda i: hashlib.sha256(f"{consulta}|{i}".encode()).hexdigest())  # embaralhado, reprodutivel
        return {"consulta": consulta, "namespaces": ns, "candidatos": [vistos[i] for i in ordem]}

    def salvar(self, consulta: str, relevantes: list[str], vistos: list[str], namespaces: list[str], categoria: str = "geral",
               expected_version: int = 0) -> dict[str, Any]:
        consulta = (consulta or "").strip()
        if not consulta:
            raise ValidacaoDominio("informe a consulta")
        if not set(relevantes) <= set(vistos):
            raise ValidacaoDominio("so e possivel marcar como relevante o que foi mostrado")
        casos, versao = self._ler()
        if versao != expected_version:
            raise ConflitoVersao(f"Os rotulos mudaram (versao {versao}); recarregue.")
        if len(casos) >= MAX_CASOS:
            raise ValidacaoDominio(f"limite de {MAX_CASOS} consultas rotuladas")
        caso = {"id": novo_id("ROT"), "consulta": consulta[:300], "namespaces": namespaces[:10], "categoria": (categoria or "geral")[:40],
                "relevantes": list(dict.fromkeys(relevantes))[:50], "vistos": list(dict.fromkeys(vistos))[:60],
                "criado_em": iso(self.relogio.agora())}
        self._gravar([*casos, caso], versao, "busca.rotulo_salvo", {"id": caso["id"], "relevantes": len(caso["relevantes"])})
        return caso

    def remover(self, id_: str, expected_version: int) -> None:
        casos, versao = self._ler()
        restantes = [c for c in casos if c["id"] != id_]
        if len(restantes) == len(casos):
            raise NaoEncontrado(f"rotulo {id_} nao encontrado")
        self._gravar(restantes, expected_version, "busca.rotulo_removido", {"id": id_})

    # ------------------------------------------------------------------ medir
    def estado(self, p: Principal, k: int = 5) -> dict[str, Any]:
        if not 1 <= k <= 10:
            raise ValidacaoDominio("k deve estar entre 1 e 10")
        casos, versao = self._ler()
        uteis = [c for c in casos if c["relevantes"]]
        saida: dict[str, Any] = {"versao": versao, "k": k, "casos": casos, "rotulados": len(casos), "com_relevantes": len(uteis),
                                 "sem_relevantes": len(casos) - len(uteis), "metricas": None, "aviso": None}
        if not uteis:
            saida["aviso"] = "Rotule algumas perguntas reais para medir a busca."
            return saida
        avaliacao = [Caso(c["consulta"], frozenset(c["relevantes"]), c.get("categoria", "geral")) for c in uteis]
        ns_de = {c["consulta"]: [n for n in c["namespaces"] if n in p.namespaces] or sorted(p.namespaces) for c in uteis}

        def ranking(expandir: bool):
            return lambda q: [i["id"] for i in self._ranking(p, q, ns_de[q], expandir)]

        saida["metricas"] = {"baseline": avaliar(ranking(False), avaliacao, k), "nova": avaliar(ranking(True), avaliacao, k)}
        if len(uteis) < MIN_CONFIAVEL:
            saida["aviso"] = (f"Amostra pequena ({len(uteis)} perguntas com algo relevante). Com menos de {MIN_CONFIAVEL} a media oscila "
                              "demais para decidir, por exemplo, adotar embeddings.")
        return saida
