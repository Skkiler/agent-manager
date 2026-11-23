"""Modularidade do segundo cerebro (ADR-028): saude do grafo, repeticoes entre notas e "organizar e deduplicar" com IA.

A ideia e a mesma da reutilizacao de codigo: se 15 notas repetem o mesmo trecho sobre A (ex.: "o sistema Funcao exige
automacao por HTTP, nao por tela"), vale mais UMA nota-modulo sobre isso, ligada a nota da entidade A, e as 15 so apontam para
ela ([[wikilink]]). Quem le qualquer uma recebe a informacao uma vez; quem pesquisa A acha o modulo.

Deterministico (sem LLM): metricas de saude (tamanho, tags, orfas, links fantasmas, repeticao) e deteccao de frases repetidas
em 2+ notas (conjunto de termos igual ou quase igual). Com IA (opcional): a Forja manda ao agente SO os aglomerados e a lista
compacta das notas; ele devolve um plano JSON (modulos, ligacoes, fusoes, divisoes, tags) que vira SUGESTOES na fila de
revisao. Nada muda sem o usuario aceitar; aceitar usa os caminhos auditaveis da memoria e do grafo.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite, novo_id
from forja.dominio.contratos import ObjetivoIn, ProjetoIn, TarefaIn, TransicaoIn
from forja.dominio.erros import ErroDominio, ValidacaoDominio
from forja.dominio.estados import EstadoTarefa
from forja.dominio.tempo import Relogio, RelogioSistema, iso
from forja.memoria.contratos import FonteIn, MemoriaAtualizaIn, MemoriaIn
from forja.memoria.modelo import ARESTAS, INATIVOS, Principal, eh_base, normalizar_tag
from forja.memoria.wikilinks import chave_titulo, extrair_wikilinks
from forja.orquestracao.organizacao import TAGS_GENERICAS, OrganizadorMemoria, jaccard, termos

PROJETO = "forja-conhecimento"
PALAVRAS_IDEAL = (60, 350)
PALAVRAS_LONGA = 600
PALAVRAS_CURTA = 25
MIN_TERMOS_FRASE = 6
LIMIAR_FRASE = 0.8
MAX_NOTAS_ANALISE = 3000
MAX_AGLOMERADOS = 25
MAX_NOTAS_NO_PEDIDO = 200
MAX_PEDIDO = 3990  # TarefaIn.descricao aceita ate 4000 caracteres
_FRASE = re.compile(r"(?<=[.!?])\s+|\n+")
_JSON = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
_CAPITALIZADA = re.compile(r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÀ-ÿ]{2,}(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÀ-ÿ]{2,})*)")
_INICIO_FRASE = frozenset({"O", "A", "Os", "As", "Use", "Para", "Se", "Em", "No", "Na", "Com", "Ver", "Este", "Esta", "Cada", "Como", "Fontes",
                           "Topico", "Tópico", "Tags", "Escopo"})
METADADOS = ("fontes:", "topico pai:", "tópico pai:", "tags:", "escopo:", "entidade:", "classificacao:", "classificação:")

# Regras de nota eficiente (mesmo texto para agentes de estudo, de organizacao e para o MCP): o agente absorve so o que precisa.
REGRAS_NOTA = (
    "NOTAS EFICIENTES (segundo cerebro da Forja): "
    "1) UM assunto por nota (atomica), com titulo especifico que diga o assunto (ex.: 'Sistema Funcao: automacoes por HTTP'). "
    f"2) Tamanho ideal {PALAVRAS_IDEAL[0]}-{PALAVRAS_IDEAL[1]} palavras; acima de {PALAVRAS_LONGA} divida em subtopicos; menos de "
    f"{PALAVRAS_CURTA} palavras sem ligacao nao se sustenta (junte a outra). "
    "3) Primeira linha = resumo de 1 frase. "
    "4) Fato sobre um sistema/biblioteca/entidade vai na nota DA ENTIDADE (ou num modulo ligado a ela), nunca repetido em cada nota de "
    "projeto: nas outras, so [[Titulo da nota]]. "
    "5) Tags: a entidade (ex.: sistema-funcao), o tipo (decisao, procedimento, armadilha) e o projeto. "
    "6) Antes de criar, BUSQUE (forja_buscar_memoria); se ja existe, complemente em vez de criar outra."
)


def palavras(texto: str) -> int:
    return len(re.findall(r"\w+", texto or ""))


def avaliar_nota(titulo: str, conteudo: str, tags: list[str] | None = None) -> list[str]:
    """Avisos de modularidade de UMA nota (deterministico). Lista vazia = nota no ponto."""
    n, links, avisos = palavras(conteudo), len(extrair_wikilinks(conteudo or "")), []
    if n > PALAVRAS_LONGA:
        avisos.append(f"nota longa ({n} palavras): divida em subtopicos ligados")
    if n < PALAVRAS_CURTA and not links:
        avisos.append(f"nota curta ({n} palavras) e sem ligacao: junte a uma nota existente ou ligue com [[...]]")
    if not [t for t in (tags or []) if t not in TAGS_GENERICAS and t not in ("agente", "automatica", "proposta")]:
        avisos.append("sem tags uteis: inclua a entidade, o tipo e o projeto")
    if len(titulo or "") < 12:
        avisos.append("titulo curto demais para achar a nota: diga o assunto")
    return avisos


def _frases(texto: str) -> list[str]:
    saida = []
    for f in _FRASE.split(texto or ""):
        f = re.sub(r"^\s*(?:[-*+]|\d+\.|#+)\s*", "", f).strip()
        if f and not f.startswith("Ver [["):
            saida.append(f)
    return saida


class Modularidade:
    def __init__(self, repo: RepositorioSqlite, memoria: Any, grafo: Any, servico: Any | None = None, relogio: Relogio | None = None,
                 principal: Principal | None = None) -> None:
        self.repo, self.memoria, self.grafo, self.servico = repo, memoria, grafo, servico
        self.relogio = relogio or RelogioSistema()
        self.principal = principal  # usado ao importar o plano sozinho quando a tarefa de organizacao termina

    def ao_finalizar(self, execucao_id: str, res: Any) -> None:
        """Tarefa de organizacao concluida: o plano vira sugestoes na fila de revisao (sem aplicar nada)."""
        if getattr(res, "estado", "") != "concluida" or self.principal is None:
            return
        with self.repo.leitura() as t:
            ex = t.obter(T.Execucao, execucao_id)
            tarefa = t.obter(T.Tarefa, ex["tarefa_id"]) if ex else None
        if not tarefa or not (tarefa.get("entrada") or {}).get("organizacao_grafo"):
            return
        texto = "\n".join([*(a.conteudo for a in getattr(res, "artefatos", []) or []), *(m.conteudo for m in getattr(res, "mensagens", []) or [])])
        try:
            self.importar_plano(self.principal, tarefa["id"], texto)
        except ErroDominio:
            pass  # sem plano valido: o usuario ve a resposta da tarefa e pode importar depois pela tela

    # ------------------------------------------------------------------ leitura
    def _notas(self, p: Principal, namespaces: list[str] | None, incluir_base: bool = False) -> list[dict[str, Any]]:
        alvo = [n for n in (namespaces or sorted(p.namespaces)) if p.pode(n)]
        if not alvo:
            raise ValidacaoDominio("sem namespace acessivel")
        with self.repo.leitura() as t:
            return [m for m in t.listar(T.Memoria, limite=MAX_NOTAS_ANALISE * 2)
                    if any(m["namespace"] == a or m["namespace"].startswith(a + "/") for a in alvo)
                    and (incluir_base or not eh_base(m["namespace"])) and m["estado"] not in {e.value for e in INATIVOS}][:MAX_NOTAS_ANALISE]

    def repeticoes(self, notas: list[dict[str, Any]], min_notas: int = 2) -> list[dict[str, Any]]:
        """Frases (>= 6 termos) que aparecem em `min_notas`+ notas, agrupadas pelo mesmo conjunto de notas. Mais economia primeiro."""
        ocorrencias: dict[frozenset[str], dict[str, Any]] = {}
        for m in notas:
            if eh_hub(m):  # texto padrao das notas-hub da Forja (projeto, grupo, entidade) nao e repeticao de conhecimento
                continue
            for f in _frases(m["conteudo"]):
                if f.lstrip(" -*").casefold().startswith(METADADOS):  # "Fontes: ...", "Topico pai: ...": metadado, nao conhecimento
                    continue
                tf = frozenset(termos(f))
                if len(tf) < MIN_TERMOS_FRASE:
                    continue
                o = ocorrencias.setdefault(tf, {"frase": f, "notas": set()})
                o["notas"].add(m["id"])
        # quase iguais (Jaccard >= 0,8): junta conjuntos que dividem termos raros (indice invertido, sem O(n^2) cego)
        chaves = list(ocorrencias)
        df = Counter(t for k in chaves for t in k)
        indice: dict[str, list[int]] = {}
        for i, k in enumerate(chaves):
            for t in sorted(k, key=lambda x: df[x])[:3]:
                indice.setdefault(t, []).append(i)
        pai = list(range(len(chaves)))

        def raiz(i: int) -> int:
            while pai[i] != i:
                pai[i] = pai[pai[i]]
                i = pai[i]
            return i

        for ids in indice.values():
            if len(ids) > 300:
                continue
            for a_i in range(len(ids)):
                for b_i in range(a_i + 1, len(ids)):
                    a, b = ids[a_i], ids[b_i]
                    if raiz(a) != raiz(b) and jaccard(chaves[a], chaves[b]) >= LIMIAR_FRASE:
                        pai[raiz(b)] = raiz(a)
        grupos: dict[int, dict[str, Any]] = {}
        for i, k in enumerate(chaves):
            g = grupos.setdefault(raiz(i), {"frases": [], "notas": set()})
            g["frases"].append(ocorrencias[k]["frase"])
            g["notas"] |= ocorrencias[k]["notas"]
        por_conjunto: dict[frozenset[str], dict[str, Any]] = {}
        for g in grupos.values():
            if len(g["notas"]) < min_notas:
                continue
            c = por_conjunto.setdefault(frozenset(g["notas"]), {"frases": [], "notas": sorted(g["notas"])})
            c["frases"].append(min(g["frases"], key=len))
        por_id = {m["id"]: m for m in notas}
        saida = []
        for c in por_conjunto.values():
            texto = " ".join(c["frases"])
            saida.append({"notas": c["notas"], "titulos": {i: por_id[i]["titulo"][:120] for i in c["notas"]}, "trecho": texto[:1200],
                          "frases": len(c["frases"]), "namespace": por_id[c["notas"][0]]["namespace"],
                          "economia_caracteres": len(texto) * (len(c["notas"]) - 1), "entidade": self._entidade(c["notas"], texto, por_id)})
        return sorted(saida, key=lambda x: -x["economia_caracteres"])

    @staticmethod
    def _entidade(ids: list[str], texto: str, por_id: dict[str, dict[str, Any]]) -> str:
        uteis = {i: OrganizadorMemoria.tags_uteis(por_id[i]["tags"]) for i in ids}
        tags = Counter(t for i in ids for t in (str(x).casefold() for x in (por_id[i]["tags"] or []))  # ordem da nota: desempate estavel
                       if t in uteis[i] and t not in ("reciclada", "automatica", "proposta", "estudado"))
        comum = [t for t, n in tags.most_common(3) if n >= max(2, len(ids) // 2)]
        if comum:
            return comum[0]
        nomes = Counter(m for m in _CAPITALIZADA.findall(texto) if m.split()[0] not in _INICIO_FRASE)
        return nomes.most_common(1)[0][0] if nomes else ""

    def saude(self, p: Principal, namespaces: list[str] | None = None, min_notas: int = 2, incluir_base: bool = False) -> dict[str, Any]:
        """Retrato do grafo: tamanho das notas, tags, orfas, links fantasmas e quanto texto se repete entre notas. Nota 0-100."""
        notas = self._notas(p, namespaces, incluir_base)
        if not notas:
            return {"notas": 0, "pontuacao": 100, "problemas": {}, "repeticoes": [], "ideal_palavras": list(PALAVRAS_IDEAL)}
        ids = {m["id"] for m in notas}
        titulos = {chave_titulo(m["titulo"]): m["id"] for m in notas}
        ligadas: set[str] = set()
        fantasmas: list[dict[str, Any]] = []
        for m in notas:
            for alvo in extrair_wikilinks(f"{m['resumo']}\n{m['conteudo']}"):
                destino = titulos.get(chave_titulo(alvo))
                if destino:
                    ligadas |= {m["id"], destino}
                else:
                    fantasmas.append({"id": m["id"], "titulo": m["titulo"][:120], "link": alvo[:120]})
            for ref in m["refs"] or []:
                if ref.startswith("memoria:") and ref[8:] in ids:
                    ligadas |= {m["id"], ref[8:]}
        with self.repo.leitura() as t:
            for lg in t.listar(T.LigacaoGrafo, limite=100_000):
                if lg["origem"] in ids or lg["destino"] in ids:
                    ligadas |= {lg["origem"], lg["destino"]}
            pendentes = sum(1 for s in t.listar(T.SugestaoMemoria, estado="pendente", limite=10_000) if p.pode(s["namespace"]))
        tam = {m["id"]: palavras(m["conteudo"]) for m in notas}
        resumo = lambda m: {"id": m["id"], "titulo": m["titulo"][:120], "namespace": m["namespace"], "palavras": tam[m["id"]]}  # noqa: E731
        longas = [resumo(m) for m in notas if tam[m["id"]] > PALAVRAS_LONGA]
        curtas = [resumo(m) for m in notas if tam[m["id"]] < PALAVRAS_CURTA and m["id"] not in ligadas]
        sem_tags = [resumo(m) for m in notas if not [x for x in (m["tags"] or []) if x not in TAGS_GENERICAS]]
        orfas = [resumo(m) for m in notas if m["id"] not in ligadas]
        reps = self.repeticoes(notas, min_notas)
        total_chars = sum(len(m["conteudo"] or "") for m in notas) or 1
        repetido = sum(r["economia_caracteres"] for r in reps)
        n = len(notas)
        pontuacao = round(100 - 30 * len(longas) / n - 15 * len(curtas) / n - 15 * len(sem_tags) / n - 20 * len(orfas) / n
                          - 20 * min(1.0, repetido / total_chars))
        ordenadas = sorted(tam.values())
        return {"notas": n, "pontuacao": max(0, pontuacao), "ideal_palavras": list(PALAVRAS_IDEAL),
                "palavras": {"media": round(sum(ordenadas) / n), "mediana": ordenadas[n // 2], "maior": ordenadas[-1]},
                "contagem": {"longas": len(longas), "curtas_soltas": len(curtas), "sem_tags": len(sem_tags), "orfas": len(orfas),
                             "links_fantasmas": len(fantasmas), "aglomerados_repetidos": len(reps), "sugestoes_pendentes": pendentes},
                "caracteres_repetidos": repetido, "percentual_repetido": round(100 * repetido / total_chars, 1),
                "problemas": {"longas": longas[:15], "curtas_soltas": curtas[:15], "sem_tags": sem_tags[:15], "orfas": orfas[:15],
                              "links_fantasmas": fantasmas[:15]},
                "repeticoes": reps[:MAX_AGLOMERADOS]}

    # ------------------------------------------------------------------ IA: plano de organizacao
    def pedir_ia(self, p: Principal, namespaces: list[str] | None = None, foco: str = "", executar: bool = True) -> dict[str, Any]:
        if self.servico is None:
            raise ValidacaoDominio("organizacao por IA indisponivel neste servidor")
        notas = self._notas(p, namespaces)
        if len(notas) < 2:
            raise ValidacaoDominio("poucas notas para organizar (precisa de 2 ou mais)")
        s = self.saude(p, namespaces)
        descricao = self._pedido(s, notas, foco)
        projeto = next(iter(self.servico.listar(T.Projeto, nome=PROJETO)), None)
        if projeto is None:
            projeto, _ = self.servico.criar_projeto(ProjetoIn(nome=PROJETO, descricao="Organizacao e deduplicacao do segundo cerebro"))
        objetivo, _ = self.servico.criar_objetivo(ObjetivoIn(projeto_id=projeto["id"], titulo="Organizar e deduplicar o segundo cerebro",
                                                             prioridade=4, criterios_sucesso=["Plano de organizacao valido"]))
        tarefa, _ = self.servico.criar_tarefa(TarefaIn(
            objetivo_id=objetivo["id"], titulo="Organizar e deduplicar o segundo cérebro", descricao=descricao[:MAX_PEDIDO],
            criterios_aceite=["Um bloco ```json``` no formato pedido", "Cada modulo cita as notas que passam a apontar para ele"],
            especialidade="conhecimento", modo="analise",
            entrada={"organizacao_grafo": {"namespaces": namespaces or sorted(p.namespaces)}}))
        for destino in (EstadoTarefa.CLASSIFICADA, EstadoTarefa.PREPARADA):
            tarefa, _ = self.servico.transicionar(tarefa["id"], TransicaoIn(para=destino, expected_version=tarefa["versao_estado"]))
        execucao = None
        if executar:
            execucao = self.servico.criar_execucao(tarefa["id"])
            self.servico.iniciar_execucao(execucao["id"], "operador")
        return {"tarefa_id": tarefa["id"], "execucao_id": execucao["id"] if execucao else None, "saude": {"pontuacao": s["pontuacao"]}}

    @staticmethod
    def _pedido(s: dict[str, Any], notas: list[dict[str, Any]], foco: str, limite: int = MAX_PEDIDO) -> str:
        """Pedido dentro do limite da tarefa (TarefaIn.descricao): primeiro os maiores trechos repetidos e as notas deles, depois
        longas e orfas, depois o resto das notas por recencia, ate caber. Com centenas de notas (achado no lote real: 611) o
        agente organiza o mais valioso agora e busca o resto com forja_buscar_memoria; a proxima rodada pega o que sobrou."""
        cabeca = ("Organize e deduplique o segundo cerebro da Forja, como se fosse refatorar codigo repetido em funcoes reutilizaveis.\n"
                  + (f"Foco pedido pelo usuario: {' '.join(foco.split())[:300]}\n" if foco.strip() else "")
                  + f"Saude atual: nota {s['pontuacao']}/100, {s['notas']} notas, {s['percentual_repetido']}% do texto repetido, "
                  f"{len(s['repeticoes'])} grupos repetidos, {s['contagem']['orfas']} orfas, {s['contagem']['longas']} longas.\n")
        fim = ("\nAs listas acima sao parciais (limite do pedido): busque o resto com forja_buscar_memoria e leia com "
               "forja_navegar_memoria (conteudo=true) so o que precisar. " + REGRAS_NOTA + "\n\n" + FORMATO)
        por_id = {m["id"]: m for m in notas}
        partes: list[str] = []
        usados: list[str] = []
        sobra = limite - len(cabeca) - len(fim)

        def caber(linha: str) -> bool:
            nonlocal sobra
            if len(linha) + 1 > sobra:
                return False
            partes.append(linha)
            sobra -= len(linha) + 1
            return True

        if s["repeticoes"] and caber("Trechos REPETIDOS em varias notas (candidatos a nota-modulo):"):
            for r in s["repeticoes"]:
                if not caber(f"- {', '.join(r['notas'][:8])} (entidade: {r['entidade'] or '?'}): \"{r['trecho'][:160]}\""):
                    break
                usados += r["notas"][:8]
        for rotulo, itens in (("Notas longas (dividir):", s["problemas"]["longas"][:6]), ("Notas sem ligacao:", s["problemas"]["orfas"][:10])):
            if itens and caber(rotulo):
                for x in itens:
                    if not caber(f"- {x['id']} {x['titulo'][:70]}"):
                        break
        recentes = [m["id"] for m in sorted(notas, key=lambda m: m["atualizado_em"], reverse=True)]
        if caber("Notas (id | pasta | titulo | tags):"):
            for mid in dict.fromkeys([*usados, *recentes]):
                m = por_id.get(mid)
                if m and not caber(f"{m['id']} | {m['namespace'].removeprefix('pessoal/')} | {m['titulo'][:70]} | {','.join((m['tags'] or [])[:4])}"):
                    break
        return cabeca + "\n".join(partes) + fim

    def importar_plano(self, p: Principal, tarefa_id: str, texto: str | None = None) -> dict[str, Any]:
        """Plano JSON do agente -> sugestoes pendentes na fila de revisao (nada e aplicado aqui)."""
        if texto is None:
            if self.servico is None:
                raise ValidacaoDominio("servico indisponivel")
            tarefa = self.servico.obter(T.Tarefa, tarefa_id)
            if not (tarefa.get("entrada") or {}).get("organizacao_grafo"):
                raise ValidacaoDominio("esta tarefa nao e um pedido de organizacao do segundo cerebro")
            texto = ""
            for a in sorted(self.servico.listar(T.Artefato, tarefa_id=tarefa_id), key=lambda a: a.get("criado_em") or "", reverse=True):
                if str(a.get("nome", "")).endswith(".md"):
                    texto = self.servico.obter_artefato(a["id"], com_conteudo=True).get("conteudo", "")
                    if "```json" in texto:
                        break
        blocos = _JSON.findall(texto or "")
        if not blocos:
            raise ValidacaoDominio("a resposta da IA ainda nao tem um bloco ```json``` (a tarefa terminou?)")
        try:
            plano = json.loads(blocos[-1])
        except json.JSONDecodeError as e:
            raise ValidacaoDominio(f"o JSON da IA esta invalido (linha {e.lineno}): {e.msg}") from e
        with self.repo.leitura() as t:
            notas = {m["id"]: m for m in t.listar(T.Memoria, limite=100_000) if p.pode(m["namespace"]) and not eh_base(m["namespace"])
                     and m["estado"] not in {e.value for e in INATIVOS}}
            existentes = {s["chave"] for s in t.listar(T.SugestaoMemoria, limite=100_000)}
        novas, recusados = [], []

        def validas(ids: Any) -> list[str]:
            return [i for i in (ids or []) if isinstance(i, str) and i in notas]

        for m in (plano.get("modulos") or [])[:30]:
            ids = validas(m.get("notas"))
            titulo, conteudo = str(m.get("titulo") or "").strip()[:200], str(m.get("conteudo") or "").strip()[:8000]
            if len(ids) < 2 or not titulo or palavras(conteudo) < 5:
                recusados.append(f"modulo '{titulo[:60]}': precisa de titulo, conteudo e 2+ notas validas")
                continue
            ns = pasta_do_modulo([notas[i]["namespace"] for i in ids])
            if ns is None:  # notas de raizes diferentes (publico x pessoal): o modulo nao tem um lugar comum
                recusados.append(f"modulo '{titulo[:60]}': notas em raizes diferentes")
                continue
            novas.append({"tipo": "modularizar", "memorias": ids, "namespace": ns,
                          "motivo": f"{len(ids)} notas repetem o mesmo conteúdo: vira a nota-módulo '{titulo}' e elas passam a apontar para ela.",
                          "dados": {"titulo": titulo, "conteudo": conteudo, "entidade": str(m.get("entidade") or "")[:120],
                                    "tags": [str(x)[:50] for x in (m.get("tags") or [])][:10], "trecho": str(m.get("trecho_repetido") or conteudo)[:3000],
                                    "titulos": {i: notas[i]["titulo"][:120] for i in ids}}})
        for lg in (plano.get("ligacoes") or [])[:100]:
            ids = validas([lg.get("origem"), lg.get("destino")])
            tipo = str(lg.get("tipo") or "RELACIONADO_A")
            if len(ids) != 2 or tipo not in ARESTAS or ids[0] == ids[1]:
                continue
            novas.append({"tipo": "ligacao", "memorias": ids, "namespace": notas[ids[0]]["namespace"],
                          "motivo": str(lg.get("motivo") or "relacionadas (organização por IA)")[:300],
                          "dados": {"tipo_ligacao": tipo, "titulos": {i: notas[i]["titulo"][:120] for i in ids}}})
        for f in (plano.get("fundir") or [])[:30]:
            venc, perd = validas([f.get("vencedora")]), validas(f.get("perdedoras"))
            if not venc or not perd:
                continue
            ids = [venc[0], *[x for x in perd if x != venc[0]]]
            novas.append({"tipo": "duplicata", "memorias": ids, "namespace": notas[venc[0]]["namespace"],
                          "motivo": str(f.get("motivo") or "falam a mesma coisa (organização por IA)")[:300],
                          "dados": {"vencedora_sugerida": venc[0], "titulos": {i: notas[i]["titulo"][:120] for i in ids}}})
        for d in (plano.get("dividir") or [])[:15]:
            ids = validas([d.get("nota")])
            partes = [x for x in (d.get("partes") or []) if isinstance(x, dict) and x.get("titulo") and x.get("conteudo")][:8]
            if not ids or len(partes) < 2:
                continue
            novas.append({"tipo": "dividir", "memorias": ids, "namespace": notas[ids[0]]["namespace"],
                          "motivo": f"Nota longa: vira {len(partes)} subtópicos ligados.",
                          "dados": {"partes": [{"titulo": str(x["titulo"])[:200], "conteudo": str(x["conteudo"])[:8000],
                                                "tags": [str(y)[:50] for y in (x.get("tags") or [])][:10]} for x in partes],
                                    "titulos": {ids[0]: notas[ids[0]]["titulo"][:120]}}})
        for tg in (plano.get("tags") or [])[:100]:
            ids = validas([tg.get("nota")])
            tags = list(dict.fromkeys(x for x in (normalizar_tag(str(x)) for x in (tg.get("tags") or [])) if x))[:8]
            if ids and [x for x in tags if x]:
                novas.append({"tipo": "tags", "memorias": ids, "namespace": notas[ids[0]]["namespace"], "motivo": f"Tags para achar a nota: {', '.join(tags)}",
                              "dados": {"tags": [x for x in tags if x], "titulos": {ids[0]: notas[ids[0]]["titulo"][:120]}}})
        criadas: Counter[str] = Counter()
        agora = iso(self.relogio.agora())
        with self.repo.escrita() as t:
            for s in novas:
                chave = f"{s['tipo']}:{','.join(sorted(s['memorias']))}:{(s['dados'] or {}).get('titulo', '')}"[:200]
                if chave in existentes:
                    continue
                existentes.add(chave)
                t.inserir(T.SugestaoMemoria, id=novo_id("SUG"), chave=chave, estado="pendente", criado_em=agora, **s)
                criadas[s["tipo"]] += 1
            t.emitir_evento("memoria.plano_organizacao", agora, {"tarefa_id": tarefa_id, "novas": dict(criadas)})
        return {"novas": dict(criadas), "total": sum(criadas.values()), "recusados": recusados}

    # ------------------------------------------------------------------ aplicar (chamado ao aceitar uma sugestao)
    def aplicar(self, p: Principal, s: dict[str, Any], ator: str) -> dict[str, Any]:
        dados = s["dados"] or {}
        if s["tipo"] == "modularizar":
            return self._modularizar(p, s["namespace"], list(s["memorias"]), dados, ator)
        if s["tipo"] == "dividir":
            return self._dividir(p, s["memorias"][0], dados, ator)
        if s["tipo"] == "tags":
            m = self.memoria.obter(p, s["memorias"][0])
            tags = list(dict.fromkeys([*(m["tags"] or []), *dados.get("tags", [])]))[:30]
            self.memoria.atualizar(p, m["id"], MemoriaAtualizaIn(expected_version=m["versao"], tags=tags, motivo="organizacao: tags"), ator)
            return {"nota": m["id"], "tags": tags}
        raise ValidacaoDominio(f"tipo de sugestao desconhecido: {s['tipo']}")

    def _nota_por_titulo(self, ns: str, titulo: str) -> dict[str, Any] | None:
        with self.repo.leitura() as t:
            return next((m for m in t.listar(T.Memoria, namespace=ns, limite=5000)
                         if m["titulo"].casefold() == titulo.casefold() and m["estado"] not in {e.value for e in INATIVOS}), None)

    def _modularizar(self, p: Principal, ns: str, ids: list[str], dados: dict[str, Any], ator: str) -> dict[str, Any]:
        titulo, entidade = dados["titulo"], (dados.get("entidade") or "").strip()
        modulo = self._nota_por_titulo(ns, titulo)
        if modulo is None:
            modulo = self.memoria.criar(p, MemoriaIn(
                tipo="semantica", titulo=titulo, resumo=_frases(dados["conteudo"])[0][:300] if _frases(dados["conteudo"]) else titulo,
                conteudo=dados["conteudo"], namespace=ns, tags=list(dict.fromkeys(["modulo", *dados.get("tags", [])]))[:30],
                fonte=FonteIn(tipo="manual"), refs=[f"memoria:{i}" for i in ids][:50], confianca=0.3), ator)
        hub = None
        if entidade:  # a nota DA ENTIDADE: pesquisas sobre o sistema acham o modulo
            hub = self._nota_por_titulo(ns, entidade) or self.memoria.criar(p, MemoriaIn(
                tipo="estrutural", titulo=entidade[:200], resumo=f"Tudo sobre {entidade}: fatos e regras que valem para todos os projetos.",
                conteudo=f"Tudo sobre {entidade}. Os subtópicos ficam ligados a esta nota.", namespace=ns,
                tags=["entidade", normalizar_tag(entidade)]), ator)
            try:
                self.grafo.ligar(p, modulo["id"], hub["id"], "SUBTOPICO_DE", "módulo da entidade", ator)
            except ErroDominio:
                pass
        alvo = [frozenset(termos(f)) for f in _frases(dados.get("trecho") or dados["conteudo"])]
        alvo = [f for f in alvo if len(f) >= 3]
        editadas, ligadas, economia = 0, 0, 0
        for i in ids:
            try:
                m = self.memoria.obter(p, i)
            except ErroDominio:
                continue
            if m["estado"] == "validado":  # nota validada nao se edita: so liga ao modulo
                try:
                    self.grafo.ligar(p, i, modulo["id"], "BASEADO_EM", "usa o módulo", ator)
                    ligadas += 1
                except ErroDominio:
                    pass
                continue
            novo = remover_trecho(m["conteudo"], alvo)
            link = f"Ver [[{titulo}]]."
            if f"[[{titulo}]]" not in novo:
                novo = (novo + "\n\n" + link).strip()
            if novo != m["conteudo"]:
                economia += max(0, len(m["conteudo"]) - len(novo))
                self.memoria.atualizar(p, i, MemoriaAtualizaIn(expected_version=m["versao"], conteudo=novo,
                                                               motivo=f"modularizacao: trecho movido para '{titulo}'"[:1000]), ator)
                editadas += 1
        return {"modulo": modulo["id"], "entidade": hub["id"] if hub else None, "editadas": editadas, "ligadas": ligadas,
                "caracteres_economizados": economia}

    def _dividir(self, p: Principal, mid: str, dados: dict[str, Any], ator: str) -> dict[str, Any]:
        m = self.memoria.obter(p, mid)
        partes = []
        for x in dados.get("partes", []):
            nota = self._nota_por_titulo(m["namespace"], x["titulo"]) or self.memoria.criar(p, MemoriaIn(
                tipo=m["tipo"], titulo=x["titulo"], resumo=(_frases(x["conteudo"]) or [x["titulo"]])[0][:300], conteudo=x["conteudo"],
                namespace=m["namespace"], tags=list(dict.fromkeys([*(m["tags"] or []), *x.get("tags", [])]))[:30],
                fonte=FonteIn(tipo="manual"), refs=[f"memoria:{mid}"], confianca=0.3), ator)
            try:
                self.grafo.ligar(p, nota["id"], mid, "SUBTOPICO_DE", "parte da nota dividida", ator)
            except ErroDominio:
                pass
            partes.append(nota)
        if m["estado"] != "validado" and partes:
            indice = (m["resumo"] or m["titulo"]) + "\n\nPartes:\n" + "\n".join(f"- [[{x['titulo']}]]" for x in partes)
            self.memoria.atualizar(p, mid, MemoriaAtualizaIn(expected_version=m["versao"], conteudo=indice, motivo="dividida em subtópicos"), ator)
        return {"nota": mid, "partes": [x["id"] for x in partes]}


def eh_hub(m: dict[str, Any]) -> bool:
    """Nota-hub criada pela Forja (indice de projeto, grupo, entidade ou topico): so organiza, o texto e padrao."""
    tags = {str(x).casefold() for x in (m.get("tags") or [])}
    return "topico" in tags or "indice" in tags or str(m.get("titulo") or "").startswith(("Projeto: ", "Grupo: ", "Projetos: "))


def pasta_do_modulo(namespaces: list[str]) -> str | None:
    """Onde a nota-modulo fica: a pasta comum das notas; se elas sao de projetos diferentes (.../projetos/a e .../projetos/b),
    a pasta 'entidades' ao lado de 'projetos' (achado no lote real: o modulo de notas de 2 projetos caia para 1 nota so)."""
    partes = [ns.split("/") for ns in namespaces if ns]
    if not partes or len({p[0] for p in partes}) > 1:
        return None
    comum: list[str] = []
    for nivel in zip(*partes, strict=False):
        if len(set(nivel)) != 1:
            break
        comum.append(nivel[0])
    if len(set(namespaces)) > 1 and "projetos" in comum:
        comum = [*comum[: comum.index("projetos")], "entidades"]
    elif len(set(namespaces)) > 1 and comum and comum[-1] == "projetos":
        comum[-1] = "entidades"
    return "/".join(comum)


def remover_trecho(conteudo: str, alvo: list[frozenset[str]], limiar: float = 0.75) -> str:
    """Tira do texto as frases parecidas com as do trecho movido para o modulo, linha a linha, preservando a estrutura Markdown
    (titulos, listas, linhas em branco). Linha que fica vazia sai."""
    saida: list[str] = []
    for linha in (conteudo or "").split("\n"):
        prefixo = re.match(r"^\s*(?:[-*+]\s+|\d+\.\s+|#+\s+|>\s*)?", linha).group(0)
        resto = linha[len(prefixo):]
        if not resto.strip() or prefixo.lstrip().startswith("#"):
            saida.append(linha)
            continue
        frases = [f for f in re.split(r"(?<=[.!?])\s+", resto) if f.strip()]
        mantidas = [f for f in frases if not any(jaccard(frozenset(termos(f)), a) >= limiar for a in alvo)]
        if len(mantidas) == len(frases):
            saida.append(linha)
        elif mantidas:
            saida.append(prefixo + " ".join(mantidas))
    texto = re.sub(r"\n{3,}", "\n\n", "\n".join(saida)).strip()
    # titulo de secao que ficou vazia sai: o proximo conteudo e um titulo do mesmo nivel ou acima (ou o fim do texto)
    linhas = texto.split("\n")
    nivel = lambda s: len(s) - len(s.lstrip("#")) if re.match(r"^#+ ", s) else 0  # noqa: E731
    i = len(linhas) - 1
    while i >= 0:
        n = nivel(linhas[i])
        if n:
            j = i + 1
            while j < len(linhas) and not linhas[j].strip():
                j += 1
            if j >= len(linhas) or 0 < nivel(linhas[j]) <= n:
                del linhas[i:j]
        i -= 1
    return re.sub(r"\n{3,}", "\n\n", "\n".join(linhas)).strip()


FORMATO = """Formato da resposta: UM bloco ```json``` com:
{"modulos": [{"titulo": "<Entidade: assunto especifico>", "entidade": "<nome do sistema/biblioteca/conceito, ex.: Sistema Funcao>",
  "conteudo": "<a informacao comum, escrita UMA vez, 60-350 palavras>", "tags": ["<entidade>", "<tipo>"],
  "trecho_repetido": "<o texto que se repete nas notas e sai delas>", "notas": ["MEM-...", "MEM-..."]}],
 "ligacoes": [{"origem": "MEM-...", "destino": "MEM-...", "tipo": "RELACIONADO_A|DEPENDE_DE|BASEADO_EM|SUBTOPICO_DE|REUTILIZAVEL_EM", "motivo": "<curto>"}],
 "fundir": [{"vencedora": "MEM-...", "perdedoras": ["MEM-..."], "motivo": "<falam exatamente a mesma coisa>"}],
 "dividir": [{"nota": "MEM-...", "partes": [{"titulo": "...", "conteudo": "...", "tags": ["..."]}]}],
 "tags": [{"nota": "MEM-...", "tags": ["entidade", "tipo", "projeto"]}]}
Regras: use SO ids da lista; um modulo so quando 2+ notas repetem a mesma informacao; nao invente fatos (o conteudo do modulo sai
das notas); prefira poucas mudancas de alto valor (no maximo 15 modulos, 50 ligacoes). Textos em portugues do Brasil."""
