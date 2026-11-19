"""Reciclagem de sessoes antigas e ponte caderno <-> segundo cerebro <-> grafo (ADR-027).

Sessao antiga = tarefa terminada (concluida, falhou, cancelada, expirada) ou sub-master encerrado, parada ha mais de N dias
(preferencia `reciclagem_dias`; 0 = desligada). Deterministico, sem LLM:

1. DESTILAR: relato curto (objetivo, resultado, decisoes do usuario, caderno por tipo, pendencias, arquivos alterados).
2. VALOR: so vira conhecimento o que tem conteudo reutilizavel (pontos >= LIMIAR_VALOR). Abaixo disso a sessao so e arquivada
   ('sem_valor'): uma nota por tarefa trivial seria ruido no segundo cerebro.
3. SEM RETRABALHO (os tres guardam conhecimento; nenhum cria copia do outro):
   - a tarefa ja tem nota (Registro ao concluir, proposta) -> a nota e ENRIQUECIDA com o caderno;
   - ha nota parecida do mesmo projeto (Jaccard de termos) -> o relato vira uma SECAO dela;
   - nota parecida ja validada (nao se edita) -> a sessao fica 'coberta' por ela; so com valor alto cria nota ligada a ela;
   - so cria nota nova quando nada cobre o assunto.
4. GRAFO: nota nova fica pendurada no topico do projeto (SUBTOPICO_DE) e ligada a nota mais proxima (RELACIONADO_A).
5. ARQUIVAR: grava a reciclagem; `reciclagem_compactar` decide o que sai do banco depois de copiado para a nota:
   nada (padrao) | caderno (itens do caderno) | detalhes (caderno + eventos detalhados das execucoes, ex. cada chamada de
   ferramenta). Pedido, respostas, decisoes e artefatos nunca sao apagados.

A ponte (`ConhecimentoTarefa`) faz o caminho inverso: a consulta do caderno de uma tarefa tambem traz as notas do projeto (o que
outras sessoes ja aprenderam) e os vizinhos delas no grafo, e o contexto inicial da tarefa inclui o namespace do projeto.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import delete

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite, novo_id
from forja.dominio.erros import ErroDominio, NaoEncontrado, ValidacaoDominio
from forja.dominio.estados import TERMINAIS
from forja.dominio.tempo import Relogio, RelogioSistema, iso
from forja.memoria.contratos import FonteIn, MemoriaAtualizaIn, MemoriaIn
from forja.memoria.modelo import INATIVOS, Principal, eh_base
from forja.observabilidade.sanitizar import sanitizar_texto
from forja.orquestracao.organizacao import jaccard, termos

log = logging.getLogger("forja.reciclagem")

LIMIAR_VALOR = 3
LIMIAR_PARECIDA = 0.5  # termos da nota x termos do relato
LIMIAR_TITULO = 0.6
LIMIAR_LIGACAO = 0.25  # abaixo de 'parecida', mas perto o bastante para ligar no grafo
MAX_POR_RODADA = 25
MAX_CONTEUDO = 20_000
INTERVALO_S = 6 * 3600
DETALHES = ("kiro.ferramenta", "agente.passo", "kiro.prompt_montado")
COMPACTAR = ("nada", "caderno", "detalhes")
_TERMINAIS = {e.value for e in TERMINAIS}
_ROTULOS = {"decisao": "Decisões", "resolvido": "Resolvido", "erro": "Erros e correções", "fato": "Fatos",
            "pendencia": "Pendências", "arquivo": "Arquivos entendidos"}


def namespace_projeto(nome: str) -> str:
    from forja.orquestracao.estudos import _slug

    return f"pessoal/projetos/{_slug(nome or 'geral')}"


@dataclass
class Relato:
    tipo: str  # tarefa | coordenacao
    alvo_id: str
    projeto_id: str | None
    projeto: str
    titulo: str
    resumo: str
    secoes: list[tuple[str, list[str]]] = field(default_factory=list)
    pontos: int = 0
    tags: list[str] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"{self.tipo}:{self.alvo_id}"

    @property
    def namespace(self) -> str:
        return namespace_projeto(self.projeto)

    def markdown(self, nivel: str = "##") -> str:
        return "\n\n".join(f"{nivel} {r}\n" + "\n".join(f"- {x}" for x in linhas) for r, linhas in self.secoes if linhas)

    def termos(self) -> set[str]:
        return termos(" ".join([self.titulo, self.resumo, *[x for _r, ls in self.secoes for x in ls]]))


def _limpo(texto: Any, n: int) -> str:
    return " ".join(sanitizar_texto(str(texto or "")).split())[:n]


class ReciclagemServico:
    def __init__(self, repo: RepositorioSqlite, memoria: Any, grafo: Any, principal: Principal,
                 topico_de: Callable[[str, str], str] | None = None, relogio: Relogio | None = None) -> None:
        self.repo = repo
        self.memoria = memoria  # ServicoMemoria
        self.grafo = grafo  # GrafoServico
        self.principal = principal
        self.topico_de = topico_de  # (namespace, nome do projeto) -> id da nota-topico do projeto (EstudoServico)
        self.relogio = relogio or RelogioSistema()
        self.dias = 30  # preferencia 'reciclagem_dias' (0 = desligada)
        self.compactar = "nada"  # preferencia 'reciclagem_compactar'
        self._mu = threading.Lock()
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ candidatas
    def _corte(self, dias: int | None = None) -> str:
        return iso(self.relogio.agora() - timedelta(days=self.dias if dias is None else dias))

    def candidatas(self, dias: int | None = None, limite: int = 200) -> list[dict[str, Any]]:
        corte = self._corte(dias)
        with self.repo.leitura() as t:
            feitas = {r["alvo_id"] for r in t.listar(T.Reciclagem, limite=1_000_000)}
            tarefas = [x for x in t.listar(T.Tarefa, ordem=T.Tarefa.atualizado_em, limite=100_000)
                       if x["estado"] in _TERMINAIS and x["atualizado_em"] <= corte and x["id"] not in feitas]
            coords = [c for c in t.listar(T.Coordenacao, tipo="submaster", estado="encerrado", limite=10_000)
                      if c["atualizado_em"] <= corte and c["id"] not in feitas]
        saida = [{"tipo": "tarefa", "id": x["id"], "titulo": x["titulo"], "estado": x["estado"], "atualizado_em": x["atualizado_em"]}
                 for x in tarefas]
        saida += [{"tipo": "coordenacao", "id": c["id"], "titulo": c["titulo"], "estado": c["estado"], "atualizado_em": c["atualizado_em"]}
                  for c in coords]
        return sorted(saida, key=lambda x: x["atualizado_em"])[:limite]

    def previa(self, dias: int | None = None, limite: int = 50) -> dict[str, Any]:
        """O que a proxima rodada faria, sem gravar nada."""
        itens = []
        for c in self.candidatas(dias, limite):
            r = self.relato(c["tipo"], c["id"])
            acao, alvo = self._destino(r)
            itens.append({**c, "pontos": r.pontos, "acao": acao, "memoria_id": (alvo or {}).get("id"),
                          "memoria_titulo": (alvo or {}).get("titulo")})
        return {"dias": self.dias if dias is None else dias, "compactar": self.compactar, "itens": itens}

    def historico(self, limite: int = 100) -> list[dict[str, Any]]:
        with self.repo.leitura() as t:
            return list(reversed(t.listar(T.Reciclagem, limite=100_000)))[:limite]

    # ------------------------------------------------------------------ destilar
    def relato(self, tipo: str, alvo_id: str) -> Relato:
        with self.repo.leitura() as t:
            if tipo == "tarefa":
                return self._relato_tarefa(t, alvo_id)
            if tipo == "coordenacao":
                return self._relato_coordenacao(t, alvo_id)
        raise ValidacaoDominio("tipo deve ser 'tarefa' ou 'coordenacao'")

    def _relato_tarefa(self, t: Any, tarefa_id: str) -> Relato:
        tarefa = t.obter(T.Tarefa, tarefa_id)
        if tarefa is None:
            raise NaoEncontrado(f"Tarefa {tarefa_id} nao encontrada.")
        projeto = t.obter(T.Projeto, tarefa["projeto_id"]) or {"nome": "geral"}
        execs = t.listar(T.Execucao, tarefa_id=tarefa_id, limite=100)
        ultimo = (execs[-1].get("resultado") or {}) if execs else {}
        cad = t.listar(T.CadernoItem, ordem=T.CadernoItem.criado_em, tarefa_id=tarefa_id, limite=300)
        respostas = [m["conteudo"] for m in t.listar(T.Mensagem, ordem=T.Mensagem.ordem, tarefa_id=tarefa_id, papel="operador", limite=200)]
        alterados: list[str] = []
        for ex in execs[-3:]:
            for e in t.eventos_da_execucao(ex["id"], 3000):
                p = e["payload"] or {}
                if e["tipo"] == "kiro.ferramenta" and p.get("tipo") in ("edit", "delete", "move") and p.get("status") == "completed":
                    tit = _limpo(p.get("titulo"), 100)
                    if tit and tit not in alterados:
                        alterados.append(tit)
        r = Relato("tarefa", tarefa_id, tarefa["projeto_id"], projeto["nome"], _limpo(tarefa["titulo"], 180),
                   _limpo(tarefa["descricao"] or tarefa["titulo"], 300), tags=["registro", "reciclada", tarefa["modo"]])
        estado = f"{tarefa['estado']}" + (f": {_limpo(tarefa['motivo_estado'], 200)}" if tarefa.get("motivo_estado") else "")
        r.secoes.append(("Sessão", [f"Estado final: {estado}", f"Encerrada em {tarefa['atualizado_em'][:10]}"]))
        resultado = _limpo(ultimo.get("resumo"), 900)
        if resultado:
            r.secoes.append(("Resultado", [resultado]))
        if respostas:
            r.secoes.append(("Decisões do desenvolvedor", [_limpo(x, 300) for x in respostas[-5:]]))
        for tipo in ("decisao", "resolvido", "erro", "fato", "pendencia", "arquivo"):
            linhas = [_limpo(i["texto"], 300) + (f" ({_limpo(i['ref'], 80)})" if i["ref"] else "") for i in cad if i["tipo"] == tipo][-8:]
            if linhas:
                r.secoes.append((_ROTULOS[tipo], linhas))
        pend = [_limpo(x, 200) for x in (ultimo.get("pendencias") or [])[:6]]
        if pend:
            r.secoes.append(("Pendências da última execução", pend))
        if alterados:
            r.secoes.append(("Alterações feitas", alterados[-10:]))
        uteis = sum(1 for i in cad if i["tipo"] in ("decisao", "resolvido", "erro", "fato"))
        r.pontos = (2 * min(len(respostas), 2) + min(uteis, 5) + (1 if len(resultado) >= 120 else 0) + (1 if pend else 0)
                    + (1 if alterados else 0) + (1 if tarefa["estado"] in ("falhou", "expirada") and tarefa.get("motivo_estado") else 0))
        return r

    def _relato_coordenacao(self, t: Any, coord_id: str) -> Relato:
        c = t.obter(T.Coordenacao, coord_id)
        if c is None:
            raise NaoEncontrado(f"Coordenacao {coord_id} nao encontrada.")
        projeto = (t.obter(T.Projeto, c["projeto_id"]) if c["projeto_id"] else None) or {"nome": "geral"}
        msgs = t.listar(T.MensagemCoordenacao, ordem=T.MensagemCoordenacao.criado_em, coordenacao_id=coord_id, limite=500)
        tarefas = t.tarefas_por_entrada("coordenacao_id", coord_id)
        r = Relato("coordenacao", coord_id, c["projeto_id"], projeto["nome"], _limpo(c["titulo"], 180),
                   _limpo(c["objetivo"] or c["titulo"], 300), tags=["registro", "reciclada", "coordenacao"])
        usuario = [_limpo(m["conteudo"], 300) for m in msgs if m["papel"] == "usuario"][-5:]
        coord = [_limpo(m["conteudo"], 300) for m in msgs if m["papel"] in ("master", "submaster")][-6:]
        if c["objetivo"]:
            r.secoes.append(("Objetivo", [_limpo(c["objetivo"], 600)]))
        if usuario:
            r.secoes.append(("Pedidos do desenvolvedor", usuario))
        if coord:
            r.secoes.append(("Coordenação", coord))
        if tarefas:
            r.secoes.append(("Tarefas", [f"{_limpo(x['titulo'], 120)} — {x['estado']}" for x in tarefas[:15]]))
        r.pontos = 2 * min(len(usuario), 2) + min(sum(1 for x in tarefas if x["estado"] == "concluida"), 3) + (1 if coord else 0)
        return r

    # ------------------------------------------------------------------ destino (sem retrabalho)
    def _notas_do_projeto(self, ns: str) -> list[dict[str, Any]]:
        if not self.principal.pode(ns) or eh_base(ns):
            return []
        with self.repo.leitura() as t:
            return [m for m in t.listar(T.Memoria, namespace=ns, limite=3000) if m["estado"] not in {e.value for e in INATIVOS}]

    def _destino(self, r: Relato) -> tuple[str, dict[str, Any] | None]:
        """('enriquecer'|'coberta'|'criar'|'sem_valor', nota alvo)."""
        notas = self._notas_do_projeto(r.namespace)
        propria = next((m for m in notas if r.ref in (m["refs"] or [])), None)
        if propria:
            return ("coberta" if propria["estado"] == "validado" else "enriquecer"), propria
        if r.pontos < LIMIAR_VALOR:
            return "sem_valor", None
        meus, tit = r.termos(), termos(r.titulo)
        melhor, nota = 0.0, None
        for m in notas:
            if "topico" in (m["tags"] or []):
                continue
            s = max(jaccard(meus, termos(" ".join([m["titulo"], m["resumo"], m["conteudo"][:3000]]))),
                    jaccard(tit, termos(m["titulo"].removeprefix("Registro:"))) * (LIMIAR_PARECIDA / LIMIAR_TITULO))
            if s > melhor:
                melhor, nota = s, m
        if nota is not None and melhor >= LIMIAR_PARECIDA:
            if nota["estado"] == "validado":
                return ("criar" if r.pontos >= 2 * LIMIAR_VALOR else "coberta"), nota
            if len(nota["conteudo"]) + 2000 > MAX_CONTEUDO:
                return "criar", nota
            return "enriquecer", nota
        return "criar", (nota if nota is not None and melhor >= LIMIAR_LIGACAO else None)

    # ------------------------------------------------------------------ gravar
    def reciclar(self, alvo_id: str | None = None, tipo: str = "tarefa", dias: int | None = None) -> dict[str, Any]:
        """Recicla UM alvo (qualquer idade, se terminado) ou a rodada das candidatas mais antigas (ate MAX_POR_RODADA)."""
        with self._mu:
            if alvo_id:
                self._exigir_terminado(tipo, alvo_id)
                alvos = [{"tipo": tipo, "id": alvo_id}]
            else:
                alvos = self.candidatas(dias, MAX_POR_RODADA)
            feitos = []
            for a in alvos:
                try:
                    feitos.append(self._reciclar_um(a["tipo"], a["id"]))
                except ErroDominio as e:
                    feitos.append({"alvo_id": a["id"], "tipo": a["tipo"], "resultado": "erro", "erro": e.mensagem[:200]})
            return {"reciclados": len([f for f in feitos if f.get("resultado") != "erro"]), "itens": feitos}

    def _exigir_terminado(self, tipo: str, alvo_id: str) -> None:
        with self.repo.leitura() as t:
            if tipo == "tarefa":
                x = t.obter(T.Tarefa, alvo_id)
                ok = x is not None and x["estado"] in _TERMINAIS
            elif tipo == "coordenacao":
                x = t.obter(T.Coordenacao, alvo_id)
                ok = x is not None and x["tipo"] == "submaster" and x["estado"] == "encerrado"
            else:
                raise ValidacaoDominio("tipo deve ser 'tarefa' ou 'coordenacao'")
            if x is None:
                raise NaoEncontrado(f"{alvo_id} nao encontrado.")
            if not ok:
                raise ValidacaoDominio("so sessoes terminadas (tarefa terminal ou sub-master encerrado) podem ser recicladas")
            if t.listar(T.Reciclagem, alvo_id=alvo_id, limite=1):
                raise ValidacaoDominio("esta sessao ja foi reciclada")

    def _reciclar_um(self, tipo: str, alvo_id: str) -> dict[str, Any]:
        r = self.relato(tipo, alvo_id)
        acao, nota = self._destino(r)
        memoria_id = (nota or {}).get("id") if acao in ("enriquecer", "coberta") else None
        resultado = {"enriquecer": "enriquecida", "coberta": "coberta", "sem_valor": "sem_valor", "criar": "criada"}[acao]
        if acao == "enriquecer" and nota is not None:
            memoria_id = self._enriquecer(nota, r)
        elif acao == "criar":
            memoria_id = self._criar(r, nota)
        compactado = self._compactar(r) if self.compactar != "nada" else "nada"
        agora = iso(self.relogio.agora())
        with self.repo.escrita() as t:
            t.inserir(T.Reciclagem, id=novo_id("REC"), tipo=tipo, alvo_id=alvo_id, projeto_id=r.projeto_id, memoria_id=memoria_id,
                      resultado=resultado, pontos=r.pontos, compactado=compactado, criado_em=agora)
            t.emitir_evento("sessao.reciclada", agora, {"tipo": tipo, "alvo_id": alvo_id, "resultado": resultado, "memoria_id": memoria_id,
                                                        "pontos": r.pontos, "compactado": compactado},
                            projeto_id=r.projeto_id, tarefa_id=alvo_id if tipo == "tarefa" else None)
        return {"tipo": tipo, "alvo_id": alvo_id, "resultado": resultado, "memoria_id": memoria_id, "pontos": r.pontos, "compactado": compactado}

    def _criar(self, r: Relato, proxima: dict[str, Any] | None) -> str:
        m = self.memoria.criar(self.principal, MemoriaIn(
            tipo="episodica" if r.tipo == "tarefa" else "decisoria", titulo=f"Registro: {r.titulo}"[:200], resumo=r.resumo,
            conteudo=r.markdown()[:MAX_CONTEUDO], namespace=r.namespace, tags=r.tags[:10],
            fonte=FonteIn(tipo="execucao", caminho=f"{'tarefas' if r.tipo == 'tarefa' else 'coordenacoes'}/{r.alvo_id}"),
            refs=[r.ref], confianca=0.2), "forja:reciclagem")
        ligacoes = []
        if self.topico_de is not None:
            try:
                ligacoes.append((self.topico_de(r.namespace, r.projeto), "SUBTOPICO_DE"))
            except ErroDominio:
                pass
        if proxima is not None and proxima["id"] != m["id"]:
            ligacoes.append((proxima["id"], "RELACIONADO_A"))
        for destino, tipo_lig in ligacoes:
            try:
                self.grafo.ligar(self.principal, m["id"], destino, tipo_lig, nota="reciclagem", ator="forja:reciclagem")
            except ErroDominio:
                pass
        return m["id"]

    def _enriquecer(self, nota: dict[str, Any], r: Relato) -> str:
        atual = self.memoria.obter(self.principal, nota["id"])
        if r.ref in (atual["refs"] or []):  # a propria nota da sessao (Registro ao concluir): entra o que faltava (caderno)
            secoes = [(rot, ls) for rot, ls in r.secoes if f"## {rot}" not in atual["conteudo"]]
            extra = Relato(r.tipo, r.alvo_id, r.projeto_id, r.projeto, r.titulo, r.resumo, secoes).markdown()
            refs = atual["refs"]
        else:  # nota parecida de outra sessao: o relato vira uma secao dela
            extra = f"## Também: {r.titulo} ({r.ref})\n" + "\n".join(
                f"- {x}" for _rot, ls in r.secoes if _rot != "Sessão" for x in ls[:3])[:3000]
            refs = [*(atual["refs"] or []), r.ref][-50:]
        if not extra.strip():
            return nota["id"]
        conteudo = (atual["conteudo"].rstrip() + "\n\n" + extra)[:MAX_CONTEUDO]
        tags = list(dict.fromkeys([*(atual["tags"] or []), "reciclada"]))[:30]
        self.memoria.atualizar(self.principal, nota["id"], MemoriaAtualizaIn(
            expected_version=atual["versao"], conteudo=conteudo, tags=tags, refs=refs, motivo=f"reciclagem de {r.ref}"), "forja:reciclagem")
        return nota["id"]

    def _compactar(self, r: Relato) -> str:
        if r.tipo != "tarefa" or self.compactar not in COMPACTAR:
            return "nada"
        with self.repo.escrita() as t:
            t.s.execute(delete(T.CadernoItem).where(T.CadernoItem.tarefa_id == r.alvo_id))
            if self.compactar == "detalhes":
                ids = [e["id"] for e in t.listar(T.Execucao, tarefa_id=r.alvo_id, limite=1000)]
                if ids:
                    t.s.execute(delete(T.Evento).where(T.Evento.execucao_id.in_(ids), T.Evento.tipo.in_(DETALHES)))
        return self.compactar

    # ------------------------------------------------------------------ segundo plano
    def iniciar(self, atraso_s: float = 120.0, intervalo_s: float = INTERVALO_S) -> None:
        if self._thread is not None:
            return

        def laco() -> None:
            if self._parar.wait(atraso_s):
                return
            while not self._parar.is_set():
                if self.dias > 0:
                    try:
                        self.reciclar()
                    except Exception as e:  # noqa: BLE001 - manutencao: tenta de novo no proximo ciclo
                        log.warning("reciclagem de sessoes falhou: %s", type(e).__name__)
                if self._parar.wait(intervalo_s):
                    return

        self._thread = threading.Thread(target=laco, daemon=True, name="forja-reciclagem")
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()


class ConhecimentoTarefa:
    """Consulta unificada para UMA tarefa: caderno dela + notas do projeto no segundo cerebro + vizinhos no grafo.

    O agente pergunta uma vez (`forja_caderno_consultar`) e recebe o que a sessao atual ja anotou e o que sessoes anteriores do
    mesmo projeto deixaram, sem duplicar nada: as notas continuam no segundo cerebro, o caderno so guarda a sessao atual."""

    def __init__(self, repo: RepositorioSqlite, caderno: Any, memoria: Any, grafo: Any, principal: Principal) -> None:
        self.repo, self.caderno, self.memoria, self.grafo, self.principal = repo, caderno, memoria, grafo, principal

    def namespace_da_tarefa(self, tarefa: dict[str, Any]) -> str | None:
        with self.repo.leitura() as t:
            p = t.obter(T.Projeto, tarefa.get("projeto_id") or "")
        return namespace_projeto(p["nome"]) if p else None

    def consultar(self, tarefa_id: str, q: str = "", tipo: str = "", amplo: bool = True, limite: int = 6) -> list[dict[str, Any]]:
        itens = [{**i, "origem": "caderno"} for i in self.caderno.listar(tarefa_id, q, tipo)]
        if not (amplo and q.strip()) or tipo:
            return itens
        with self.repo.leitura() as t:
            tarefa = t.obter(T.Tarefa, tarefa_id)
        ns = self.namespace_da_tarefa(tarefa or {})
        if not ns or not self.principal.pode(ns):
            return itens
        try:
            r = self.memoria.buscar(self.principal, q, [ns], fontes=("memoria",), limite=limite)
        except ErroDominio:
            return itens
        vistos = set()
        for x in r.get("resultados") or []:
            if x.get("origem") != "memoria" or (tarefa_id and f"tarefa:{tarefa_id}" in (x.get("refs") or [])):
                continue
            vistos.add(x["id"])
            trecho = " ".join(str(x.get("trecho") or x.get("resumo") or "").replace("«", "").replace("»", "").split())[:300]
            itens.append({"origem": "memoria", "tipo": "memoria", "id": x["id"], "texto": f"{x.get('titulo')}: {trecho}", "ref": x["id"],
                          "estado": x.get("estado")})
        for mid in list(vistos)[:3]:  # 1 salto no grafo: o topico e as notas ligadas (so titulo; o agente navega se precisar)
            try:
                viz = self.grafo.links(self.principal, mid)
            except ErroDominio:
                continue
            for lig in (viz.get("saida") or []) + (viz.get("entrada") or []):
                outro, tit = lig.get("id"), lig.get("titulo")
                if outro and not str(outro).startswith("?") and outro not in vistos and tit:
                    vistos.add(outro)
                    itens.append({"origem": "grafo", "tipo": "memoria", "id": outro, "texto": f"{tit} ({lig.get('tipo')} de {mid})",
                                  "ref": outro})
        return itens
