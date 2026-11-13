"""Base de conhecimento INICIAL da Forja (segundo cerebro padrao) e navegacao por topicos.

A base vive em `forja/conhecimento_base/**/*.md` (versionada, curada, sem dado de empresa). Cada arquivo e UMA nota curta com
frontmatter:

    ---
    titulo: SOLID
    pai: Engenharia de software          # topico de cima (vira ligacao SUBTOPICO_DE)
    tags: poo, design
    tipo: semantica                      # semantica | procedimental | estrutural | decisoria
    relacionados: Padroes de projeto; Codigo limpo
    ---
    corpo em Markdown, com [[wikilinks]] para notas irmas.

Organizacao: um topico complexo vira uma nota-indice CURTA + varias subnotas pequenas ligadas. O agente recebe so o que
precisa (busca + resumo) e, se precisar de mais, navega pelos subtopicos e relacionados (`navegar`), sem carregar o resto.

Epistemologia (ADR-020): a base entra como `validado` por CURADORIA (fonte = arquivo versionado + testes de formato), nao por
evidencia de tarefa. E a unica excecao; tudo que o usuario ou o agente aprende nasce `candidato`. A base e somente leitura
(namespace publico/forja-base): o usuario complementa em namespaces proprios.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete

from forja.adapters.sqlite import memoria_fts as fts
from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.repositorio import RepositorioSqlite, Tx, novo_id
from forja.dominio.tempo import RelogioSistema, iso
from forja.memoria.modelo import BASE_NS, Principal, TipoMemoria, eh_base

log = logging.getLogger("forja.memoria.base")
RAIZ_BASE = Path(__file__).resolve().parents[1] / "conhecimento_base"
CURADORIA = "curadoria-forja"
MAX_CORPO = 6000
_FRONT = re.compile(r"^---\s*\n(?P<cab>.*?)\n---\s*\n(?P<corpo>.*)$", re.DOTALL)


@dataclass(frozen=True)
class NotaBase:
    caminho: str  # relativo a conhecimento_base, com '/'
    titulo: str
    corpo: str
    pai: str = ""
    tags: tuple[str, ...] = ()
    tipo: str = "semantica"
    relacionados: tuple[str, ...] = field(default_factory=tuple)

    @property
    def id(self) -> str:  # estavel: arquivo + titulo (renomear a nota cria outra; a antiga sai na proxima semeadura)
        chave = f"{self.caminho}#{self.titulo.casefold()}"
        return "MEM-BASE-" + hashlib.sha1(chave.encode(), usedforsecurity=False).hexdigest()[:12]

    @property
    def hash(self) -> str:
        bruto = "\x1f".join([self.titulo, self.pai, ",".join(self.tags), self.tipo, ";".join(self.relacionados), self.corpo])
        return hashlib.sha256(bruto.encode()).hexdigest()

    @property
    def resumo(self) -> str:
        """1a frase util do corpo (o que vai para o contexto); o corpo inteiro so sob demanda."""
        for linha in self.corpo.splitlines():
            s = linha.strip().lstrip("#-* ").strip()
            if s and not s.startswith(("[[", "|", "```")):
                return s[:300]
        return self.titulo


SEPARADOR = re.compile(r"^\+\+\+\s*$", re.MULTILINE)  # varias notas pequenas no mesmo arquivo da area


def ler_arquivo(arquivo: Path, raiz: Path = RAIZ_BASE) -> list[NotaBase]:
    blocos = [b.strip() for b in SEPARADOR.split(arquivo.read_text(encoding="utf-8").replace("\r\n", "\n")) if b.strip()]
    rel = arquivo.resolve().relative_to(raiz.resolve()).as_posix()
    return [ler_nota_texto(b + "\n", rel) for b in blocos]


def ler_nota(arquivo: Path, raiz: Path = RAIZ_BASE) -> NotaBase:
    return ler_arquivo(arquivo, raiz)[0]


def ler_nota_texto(texto: str, rel: str) -> NotaBase:
    m = _FRONT.match(texto)
    if not m:
        raise ValueError(f"{rel}: nota sem frontmatter")
    arquivo = Path(rel)
    cab: dict[str, str] = {}
    for linha in m["cab"].splitlines():
        if ":" in linha:
            k, v = linha.split(":", 1)
            cab[k.strip().casefold()] = v.split("#", 1)[0].strip()
    if not cab.get("titulo"):
        raise ValueError(f"{arquivo.name}: frontmatter sem 'titulo'")
    tipo = cab.get("tipo") or "semantica"
    if tipo not in {t.value for t in TipoMemoria}:
        raise ValueError(f"{arquivo.name}: tipo invalido {tipo!r}")
    corpo = m["corpo"].strip()
    if len(corpo) > MAX_CORPO:
        raise ValueError(f"{arquivo.name}: corpo maior que {MAX_CORPO} caracteres (divida em subtopicos)")
    return NotaBase(rel, cab["titulo"][:200], corpo, cab.get("pai", "")[:200],
                    tuple(t.strip()[:50] for t in cab.get("tags", "").split(",") if t.strip())[:15], tipo,
                    tuple(r.strip()[:200] for r in cab.get("relacionados", "").split(";") if r.strip())[:10])


def carregar(raiz: Path = RAIZ_BASE) -> list[NotaBase]:
    notas = [n for a in sorted(raiz.rglob("*.md")) for n in ler_arquivo(a, raiz)] if raiz.is_dir() else []
    vistos: set[str] = set()
    for n in notas:
        if n.titulo.casefold() in vistos:
            raise ValueError(f"titulo duplicado na base: {n.titulo!r}")
        vistos.add(n.titulo.casefold())
    return notas


RAIZ_PACOTES = Path(__file__).resolve().parents[1] / "conhecimento_pacotes"
_NOME_PACOTE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def pacotes_disponiveis(raiz: Path = RAIZ_PACOTES) -> list[dict[str, Any]]:
    """Pacotes de conhecimento OPCIONAIS (forja/conhecimento_pacotes/<nome>/*.md + DESCRICAO.txt). Curados e versionados como a
    base; instalados sob demanda no namespace somente leitura publico/forja-base/<nome>."""
    if not raiz.is_dir():
        return []
    saida = []
    for d in sorted(p for p in raiz.iterdir() if p.is_dir() and _NOME_PACOTE.match(p.name)):
        desc = (d / "DESCRICAO.txt").read_text(encoding="utf-8").strip()[:300] if (d / "DESCRICAO.txt").is_file() else d.name
        saida.append({"id": d.name, "descricao": desc, "notas": sum(len(ler_arquivo(a, d)) for a in sorted(d.glob("*.md")))})
    return saida


def sincronizar_pacotes(repo: RepositorioSqlite, escolhidos: list[str], raiz: Path = RAIZ_PACOTES) -> dict[str, dict[str, int]]:
    """Instala os pacotes escolhidos e REMOVE os demais (desmarcar = desinstalar). Idempotente."""
    disponiveis = {p["id"] for p in pacotes_disponiveis(raiz)}
    res = {}
    for nome in sorted(disponiveis):
        res[nome] = semear(repo, raiz / nome, f"{BASE_NS}/{nome}", origem=f"forja/conhecimento_pacotes/{nome}",
                           vazio=nome not in set(escolhidos))
    return res


def semear(repo: RepositorioSqlite, raiz: Path = RAIZ_BASE, ns: str = BASE_NS, origem: str = "forja/conhecimento_base",
           vazio: bool = False) -> dict[str, int]:
    """Idempotente: insere o que falta, atualiza o que mudou (por hash), remove o que saiu da base. Recria as ligacoes.
    `ns`/`origem`: pacotes opcionais usam um subnamespace da base; `vazio` desinstala (remove tudo do namespace)."""
    notas = [] if vazio else carregar(raiz)
    if ns != BASE_NS:  # ids de pacote nunca colidem com a base nem entre pacotes
        notas = [NotaBase(f"{ns}:{n.caminho}", n.titulo, n.corpo, n.pai, n.tags, n.tipo, n.relacionados) for n in notas]
    agora = iso(RelogioSistema().agora())
    titulos = {n.titulo.casefold(): n.id for n in notas}
    res = {"novas": 0, "atualizadas": 0, "inalteradas": 0, "removidas": 0, "ligacoes": 0}
    with repo.escrita() as t:
        if ns != BASE_NS and notas:  # o pacote pode pendurar topicos na base (ex.: pai 'Python')
            titulos = {m["titulo"].casefold(): m["id"] for m in t.listar(T.Memoria, namespace=BASE_NS, limite=10_000)} | titulos
        existentes = {m["id"]: m for m in t.listar(T.Memoria, namespace=ns, limite=10_000)}
        for n in notas:
            m = existentes.get(n.id)
            if m and (m.get("fonte") or {}).get("hash") == n.hash:
                res["inalteradas"] += 1
                continue
            campos = dict(tipo=n.tipo, titulo=n.titulo, resumo=n.resumo, conteudo=n.corpo, namespace=ns, sensibilidade="publico",
                          fonte={"tipo": "documento", "repositorio": "forja", "commit": "",
                                 "caminho": f"{origem}/{n.caminho.split(':', 1)[-1]}", "hash": n.hash},
                          precondicoes=[], estado="validado", validado_por=CURADORIA, validade_inicio=agora, validade_fim=None,
                          confianca=0.9, tags=["base", *n.tags], refs=[], afirma=None, necessita_revalidacao=False,
                          substituida_por=None, hash_conteudo=n.hash, sinalizadores={"pii_redigida": [], "suspeita_injecao": []},
                          expira_em=None, atualizado_em=agora)
            if m:
                t.atualizar(T.Memoria, n.id, versao=m["versao"] + 1, **campos)
                res["atualizadas"] += 1
            else:
                t.inserir(T.Memoria, id=n.id, versao=1, criado_em=agora, **campos)
                res["novas"] += 1
            fts.memoria_indexar(t, t.obter(T.Memoria, n.id))  # type: ignore[arg-type]
        for mid in set(existentes) - {n.id for n in notas}:
            fts.memoria_remover(t, mid)
            t.s.execute(delete(T.Memoria).where(T.Memoria.id == mid))
            res["removidas"] += 1
        t.s.execute(delete(T.LigacaoGrafo).where(T.LigacaoGrafo.namespace == ns))
        for n in notas:
            alvos = ([("SUBTOPICO_DE", n.pai)] if n.pai else []) + [("RELACIONADO_A", r) for r in n.relacionados]
            for tipo, titulo in alvos:
                destino = titulos.get(titulo.casefold())
                if destino and destino != n.id:
                    t.inserir(T.LigacaoGrafo, id=novo_id("LIG"), origem=n.id, destino=destino, tipo=tipo, namespace=ns,
                              nota="", criado_por=CURADORIA, criado_em=agora)
                    res["ligacoes"] += 1
        if res["novas"] or res["atualizadas"] or res["removidas"]:
            t.emitir_evento("memoria.base_semeada", agora, {"namespace": ns, **{k: v for k, v in res.items()}})
    return res


# ------------------------------------------------------------------ navegacao (topico -> subtopicos -> relacionados)
def _resumo(m: dict[str, Any]) -> dict[str, Any]:
    return {"id": m["id"], "titulo": m["titulo"], "resumo": (m["resumo"] or "")[:300], "estado": m["estado"],
            "base": eh_base(m["namespace"])}


def navegar(repo: RepositorioSqlite, p: Principal, ref: str, incluir_conteudo: bool = False) -> dict[str, Any]:
    """Um topico e SO a vizinhanca imediata: pai, subtopicos e relacionados, cada um com titulo e resumo (sem corpo).
    `ref` = id da memoria ou titulo exato. Respeita a ACL em cada ponta (sem oraculo de existencia)."""
    from forja.dominio.erros import NaoEncontrado

    with repo.leitura() as t:
        m = t.obter(T.Memoria, ref) if ref.startswith("MEM-") else None
        if m is None:
            m = next((x for x in t.listar(T.Memoria, titulo=ref, limite=20) if p.pode(x["namespace"])), None)
            if m is None:
                m = next((x for x in t.listar(T.Memoria, limite=20_000) if x["titulo"].casefold() == ref.casefold()
                          and p.pode(x["namespace"])), None)
        if m is None or not p.pode(m["namespace"]):
            raise NaoEncontrado(f"Topico {ref!r} nao encontrado.")
        ligs = t.listar(T.LigacaoGrafo, origem=m["id"], limite=500) + t.listar(T.LigacaoGrafo, destino=m["id"], limite=500)

        def ponta(i: str) -> dict[str, Any] | None:
            x = t.obter(T.Memoria, i)
            return _resumo(x) if x and p.pode(x["namespace"]) and x["estado"] not in ("revogado", "substituido") else None

        pai = [ponta(lg["destino"]) for lg in ligs if lg["tipo"] == "SUBTOPICO_DE" and lg["origem"] == m["id"]]
        filhos = [ponta(lg["origem"]) for lg in ligs if lg["tipo"] == "SUBTOPICO_DE" and lg["destino"] == m["id"]]
        rel = [ponta(lg["destino"] if lg["origem"] == m["id"] else lg["origem"]) for lg in ligs if lg["tipo"] != "SUBTOPICO_DE"]
    saida = {**_resumo(m), "tags": m["tags"] or [], "pai": [x for x in pai if x], "subtopicos": sorted([x for x in filhos if x], key=lambda x: x["titulo"]),
             "relacionados": list({x["id"]: x for x in rel if x}.values())}
    if incluir_conteudo:
        saida["conteudo"] = m["conteudo"][:MAX_CORPO]
        saida["fonte"] = m.get("fonte")
    return saida


def subtopicos(t: Tx, memoria_id: str, p: Principal, limite: int = 6) -> list[str]:
    """Titulos dos subtopicos (barato: usado pelo construtor de contexto para 'apontar o caminho' sem carregar nada)."""
    nomes = []
    for lg in t.listar(T.LigacaoGrafo, destino=memoria_id, tipo="SUBTOPICO_DE", limite=limite * 2):
        x = t.obter(T.Memoria, lg["origem"])
        if x and p.pode(x["namespace"]):
            nomes.append(x["titulo"])
    return sorted(nomes)[:limite]
