"""Alimentacao em LOTE do segundo cerebro (ADR-029): uma pasta com varios projetos vira conhecimento organizado em pastas.

Para cada projeto descoberto (pasta com marcadores de codigo; pastas-grupo com 2+ projetos viram um hub de grupo):
1. Deterministico, sem IA: indexa o codigo (simbolos e trechos, PII redigida) e cria a nota-hub "Projeto: <nome>" com stack,
   estrutura, pontos de entrada e dependencias (so nomes de pacotes). Nada de logs, dados, entrada/saida, .env ou chaves.
2. Com IA (opcional): um estudo do Kiro por projeto (somente leitura, pastas de dados negadas pelo mediador). As notas voltam
   classificadas por escopo: do projeto, de ENTIDADE (sistema/orgao/regra compartilhada: uma nota so, ligada a cada projeto) ou
   GENERICA (tecnica reutilizavel). Ver `EstudoServico.criar_notas`.

Pastas (tudo em `pessoal`; `publico` e o framework inicial):
  pessoal/empresa/<empresa_id>/projetos/<projeto>   automacoes da empresa
  pessoal/interno/<interno_id>/projetos/<projeto>   projetos proprios
  .../entidades                                     sistemas e regras compartilhadas entre projetos do mesmo escopo
  pessoal/geral                                     tecnicas reutilizaveis em qualquer projeto

Roda em segundo plano, N estudos por vez, ate o teto de creditos medidos. O estado fica em `configuracao` (`alimentacao_lote`).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from forja.adapters.sqlite import tabelas as T
from forja.dominio.erros import ErroDominio, ValidacaoDominio
from forja.dominio.tempo import Relogio, RelogioSistema, iso
from forja.memoria import indexador
from forja.memoria.contratos import FonteIn, IngerirIn, MemoriaIn
from forja.memoria.modelo import Principal, validar_namespace
from forja.seguranca.acoes import caminho_sensivel
from forja.seguranca.pastas import aplicar, protegido

log = logging.getLogger("forja.alimentacao")
CHAVE_ESTADO = "alimentacao_lote"
MAX_NIVEL = 4
MAX_PROJETOS = 150
MAX_ARQUIVOS_CONTAGEM = 20_000
EXTENSOES = [".py", ".md", ".js", ".ts", ".html", ".css", ".sql", ".ps1", ".sh", ".toml", ".yaml", ".yml", ".rst"]
# pastas que o agente de estudo nunca abre (dados de clientes, saidas, logs, empacotados)
IGNORAR_AGENTE = ["logs", "log", "dados", "data", "entrada", "saida", "output", "outputs", "dist", "build", ".venv", "venv",
                  "node_modules", "__pycache__", "backups", "downloads", "uploads", "temp", "tmp"]
FORTES_ARQ = {"pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "package.json", "manage.py", "main.py", "app.py",
              "alembic.ini", "dockerfile", "pom.xml", "go.mod", "cargo.toml"}
FORTES_DIR = {"src", "app"}
CODIGO = {".py", ".js", ".ts", ".cs", ".java", ".go", ".rs", ".ps1", ".html"}
_PREFIXO = re.compile(r"^\s*[\d.]+\s*(?:cod|area|código|codigo)?\s*-\s*", re.IGNORECASE)
_SLUG = re.compile(r"[^a-z0-9._-]+")
_DEP = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.\-]*)")
LINGUAGEM = {".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".html": "HTML", ".css": "CSS", ".sql": "SQL", ".ps1": "PowerShell",
             ".cs": "C#", ".java": "Java", ".go": "Go", ".rs": "Rust", ".sh": "Shell", ".qml": "QML"}
Slug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,40}$")]


class LoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    raiz: Annotated[str, Field(min_length=3, max_length=500)]
    empresa_id: Slug = "trabalho"
    interno_id: Slug = "proprios"
    # trechos do caminho que marcam projeto PROPRIO/interno (ex.: "Estudos e projetos pessoais"); o resto usa escopo_padrao
    interno_contem: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=20)
    escopo_padrao: Literal["empresa", "interno"] = "empresa"
    excluir: list[Annotated[str, Field(max_length=500)]] = Field(default_factory=list, max_length=50)
    indexar: bool = True
    estudar: bool = True
    reestudar: bool = False
    paralelo: int = Field(2, ge=1, le=4)
    teto_creditos: float = Field(300.0, ge=0, le=1000)
    foco: Annotated[str, Field(max_length=300)] = ""
    limite_projetos: int = Field(MAX_PROJETOS, ge=1, le=MAX_PROJETOS)


@dataclass
class Projeto:
    caminho: str
    nome: str
    slug: str
    escopo: str
    namespace: str
    grupo: str = ""
    linguagens: dict[str, int] = field(default_factory=dict)
    arquivos: int = 0
    estrutura: list[str] = field(default_factory=list)
    entradas: list[str] = field(default_factory=list)
    dependencias: list[str] = field(default_factory=list)
    readme: str = ""


def nome_projeto(pasta: str) -> str:
    return _PREFIXO.sub("", pasta).strip() or pasta.strip()


def slug(texto: str) -> str:
    sem = "".join(c for c in unicodedata.normalize("NFKD", texto.casefold()) if not unicodedata.combining(c))
    s = _SLUG.sub("-", sem).strip("-._")[:41].strip("-._")
    return s if s and s[0].isalnum() else ("p-" + s)[:41] if s else "projeto"


def _oculta(nome: str) -> bool:
    """'.git', '.venv'... sao ocultas; '.0. Historico' (numeracao do usuario) nao."""
    return nome.startswith(".") and not nome[1:2].isdigit()


def _filhos(p: Path) -> list[Path]:
    try:
        return sorted((c for c in p.iterdir() if c.is_dir() and not c.is_symlink() and not _oculta(c.name)
                       and c.name.casefold() not in indexador.IGNORAR_DIRS and not protegido(c)), key=lambda c: c.name.casefold())
    except OSError:
        return []


def _nomes(p: Path) -> set[str]:
    try:
        return {c.name.casefold() for c in p.iterdir()}
    except OSError:
        return set()


def _forte(p: Path) -> bool:
    n = _nomes(p)
    return bool(n & FORTES_ARQ or n & FORTES_DIR)


def _termos(nome: str) -> set[str]:
    return {x for x in re.split(r"[^a-z0-9]+", slug(nome_projeto(nome))) if len(x) >= 4 and not x.isdigit()}


def _mesmo_sistema(pasta: Path, filhos: list[Path]) -> bool:
    """Pasta-grupo: nome com prefixo de codigo ('2.4. Cod - rpa-gateway') ou termo em comum com os subprojetos."""
    if re.match(r"^\s*[\d.]*\s*(cod|código|codigo|area|área)\s*-", pasta.name, re.IGNORECASE):
        return True
    proprios = _termos(pasta.name)
    return bool(proprios) and any(proprios & _termos(f.name) for f in filhos)


COMPONENTES = {"src", "app", "tests", "test", "config", "scripts", "docs", "doc", "cli", "release", "framework", "ui", "lib", "core",
               "utils", "manual", "rules", "templates", "static", "assets", "public", "bin", "tools", "examples", "notebooks"}


def _tem_codigo(p: Path, nivel: int = 0) -> bool:
    """Ha codigo em ate 4 niveis (fora de pastas ignoradas)? Um projeto sem marcador na raiz continua sendo projeto."""
    try:
        itens = list(p.iterdir())
    except OSError:
        return False
    if any(i.is_file() and i.suffix.casefold() in CODIGO for i in itens):
        return True
    return nivel < 3 and any(_tem_codigo(i, nivel + 1) for i in itens if i.is_dir() and not i.is_symlink() and not _oculta(i.name)
                             and i.name.casefold() not in indexador.IGNORAR_DIRS)


def _eh_projeto(p: Path) -> bool:
    n = _nomes(p)
    return _forte(p) or any(Path(x).suffix in CODIGO for x in n) or "readme.md" in n


class AlimentacaoLote:
    def __init__(self, servico: Any, memoria: Any, grafo: Any, estudos: Any, politica: Any, principal: Principal,
                 relogio: Relogio | None = None, raiz_forja: Path | None = None) -> None:
        self.servico, self.memoria, self.grafo, self.estudos = servico, memoria, grafo, estudos
        self.politica = politica  # () -> PoliticaPastas: a raiz precisa estar nas pastas permitidas pelo usuario
        self.principal = principal
        self.relogio = relogio or RelogioSistema()
        self.raiz_forja = (raiz_forja or Path(__file__).resolve().parents[2]).resolve()
        self.intervalo = 5.0  # segundos entre consultas ao estado das execucoes
        self.espera_max_s = 45 * 60  # um estudo parado (ex.: esperando aprovacao) libera a vaga depois disso
        self._thread: threading.Thread | None = None
        self._parar = threading.Event()
        self._mu = threading.Lock()

    # ------------------------------------------------------------------ descoberta (deterministica)
    def _validar_raiz(self, raiz: str) -> Path:
        p = Path(raiz).expanduser()
        pol = self.politica() if self.politica else None
        if pol is None or not pol.ativa or not pol.permite(p):
            raise ValidacaoDominio("A pasta precisa estar entre as pastas permitidas (Configuracoes > Privacidade).")
        if not p.is_dir():
            raise ValidacaoDominio("Pasta inexistente.")
        return p.resolve()

    def _escopo(self, d: LoteIn, caminho: Path) -> str:
        texto = str(caminho).casefold()
        return "interno" if any(x.casefold() in texto for x in d.interno_contem if x.strip()) else d.escopo_padrao

    def namespace(self, d: LoteIn, escopo: str, s: str = "") -> str:
        base = f"pessoal/empresa/{d.empresa_id}" if escopo == "empresa" else f"pessoal/interno/{d.interno_id}"
        return validar_namespace(f"{base}/projetos/{s}" if s else base)

    def descobrir(self, d: LoteIn) -> dict[str, Any]:
        raiz = self._validar_raiz(d.raiz)
        excluir = [x.casefold() for x in d.excluir if x.strip()]
        projetos: list[Projeto] = []
        ignorados: list[dict[str, str]] = []
        usados: set[str] = set()

        def pular(c: Path) -> str:
            if c.resolve() == self.raiz_forja or self.raiz_forja in c.resolve().parents:
                return "a propria Forja (ja esta na base)"
            if any(x == c.name.casefold() or x in str(c).casefold() for x in excluir):
                return "excluida no pedido"
            pol = self.politica() if self.politica else None
            if pol is not None and not pol.permite(c):
                return "pasta proibida"
            return ""

        def visitar(p: Path, nivel: int, grupo: str) -> None:
            for c in _filhos(p):
                if len(projetos) >= d.limite_projetos:
                    return
                motivo = pular(c)
                if motivo:
                    ignorados.append({"caminho": str(c), "motivo": motivo})
                    continue
                # partes internas (src, tests, config...) nunca fazem de uma pasta um grupo: o projeto e a pasta inteira
                subprojetos = [x for x in _filhos(c) if x.name.casefold() not in COMPONENTES and (_eh_projeto(x) or _tem_codigo(x))]
                fortes = [x for x in subprojetos if _forte(x) and _tem_codigo(x)]
                # pasta de categoria (sem codigo na raiz) ou sistema com 2+ projetos completos dentro (front + back...)
                if nivel < MAX_NIVEL and (len(fortes) >= 2 or (subprojetos and not _eh_projeto(c))):
                    # pasta com 2+ projetos: GRUPO quando os nomes tem termo em comum (front/back/admin do mesmo sistema);
                    # senao e so uma pasta de categoria (ex.: "Historico") e os projetos ficam soltos
                    visitar(c, nivel + 1, nome_projeto(c.name) if _mesmo_sistema(c, subprojetos) else grupo)
                elif _eh_projeto(c) or _tem_codigo(c):
                    nome = nome_projeto(c.name)
                    s = slug(nome)
                    base = s
                    i = 2
                    while s in usados:
                        s = f"{base[:38]}-{i}"
                        i += 1
                    usados.add(s)
                    escopo = self._escopo(d, c)
                    caminho_ns = f"{slug(grupo)}/{s}" if grupo else s
                    projetos.append(self._analisar(Projeto(str(c), nome, s, escopo, self.namespace(d, escopo, caminho_ns), grupo)))
                elif nivel < MAX_NIVEL and _filhos(c):
                    visitar(c, nivel + 1, grupo)
                else:
                    ignorados.append({"caminho": str(c), "motivo": "sem codigo"})

        visitar(raiz, 0, "")
        return {"raiz": str(raiz), "projetos": [asdict(p) for p in projetos], "ignorados": ignorados,
                "por_escopo": dict(Counter(p.escopo for p in projetos))}

    def _analisar(self, pr: Projeto) -> Projeto:
        raiz = Path(pr.caminho)
        exts: Counter[str] = Counter()
        n = 0
        for c in self._percorrer(raiz):
            exts[c.suffix.casefold()] += 1
            n += 1
            if n >= MAX_ARQUIVOS_CONTAGEM:
                break
        pr.arquivos = sum(v for k, v in exts.items() if k in LINGUAGEM)
        pr.linguagens = {LINGUAGEM[k]: v for k, v in exts.most_common() if k in LINGUAGEM}
        pr.estrutura = [c.name + "/" for c in _filhos(raiz)][:15]
        nomes = _nomes(raiz)
        pr.entradas = [x for x in ("main.py", "app.py", "manage.py", "run.py", "__main__.py", "index.js", "server.js") if x in nomes]
        for sub in ("src", "app"):
            if (raiz / sub).is_dir():
                pr.entradas += [f"{sub}/{x}" for x in ("main.py", "app.py", "__main__.py") if x in _nomes(raiz / sub)]
        pr.dependencias = self._dependencias(raiz)[:25]
        pr.readme = self._readme(raiz)
        return pr

    @staticmethod
    def _percorrer(raiz: Path) -> Any:
        pilha = [raiz]
        while pilha:
            atual = pilha.pop()
            try:
                itens = list(atual.iterdir())
            except OSError:
                continue
            for c in itens:
                if c.is_symlink():
                    continue
                if c.is_dir():
                    if c.name.casefold() not in indexador.IGNORAR_DIRS and not _oculta(c.name) and c.name.casefold() not in IGNORAR_AGENTE:
                        pilha.append(c)
                elif not caminho_sensivel(c.name):
                    yield c

    @staticmethod
    def _ler(arq: Path, limite: int = 200_000) -> str:
        try:
            if arq.is_file() and not arq.is_symlink() and arq.stat().st_size <= limite and not caminho_sensivel(arq.name):
                return arq.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
        return ""

    def _dependencias(self, raiz: Path) -> list[str]:
        """So NOMES de pacotes (sem versoes, indices ou URLs: um indice privado pode ter credencial)."""
        nomes: list[str] = []
        for linha in self._ler(raiz / "requirements.txt").splitlines():
            linha = linha.split("#", 1)[0].strip()
            if not linha or linha.startswith("-") or "://" in linha or "@" in linha:
                continue
            m = _DEP.match(linha)
            if m:
                nomes.append(m.group(1).casefold())
        pj = self._ler(raiz / "package.json")
        if pj:
            try:
                dados = json.loads(pj)
                for chave in ("dependencies", "devDependencies"):
                    nomes += [str(k)[:60] for k in (dados.get(chave) or {}) if isinstance(k, str)]
            except (ValueError, AttributeError):
                pass
        py = self._ler(raiz / "pyproject.toml")
        bloco = re.search(r"(?ms)^dependencies\s*=\s*\[(.*?)\]", py)
        if bloco:
            nomes += [m.group(1).casefold() for m in (_DEP.match(x.strip().strip("\"',")) for x in bloco.group(1).splitlines()) if m]
        return list(dict.fromkeys(n for n in nomes if n))

    def _readme(self, raiz: Path) -> str:
        for nome in ("README.md", "readme.md", "Readme.md", "README.txt"):
            texto = self._ler(raiz / nome, 300_000)
            if texto:
                for bloco in re.split(r"\n\s*\n", texto):
                    limpo = " ".join(x.strip() for x in bloco.splitlines() if x.strip() and not x.lstrip().startswith(("#", "!", "[!", "<", "|", "```")))
                    if len(limpo) >= 40:
                        return limpo[:500]
        return ""

    # ------------------------------------------------------------------ notas deterministicas
    def _hub(self, ns: str, titulo: str, conteudo: str, tags: list[str], pai: str | None, tipo_lig: str = "SUBTOPICO_DE") -> str:
        with self.memoria.repo.leitura() as t:
            achada = next((m for m in t.listar(T.Memoria, namespace=ns, titulo=titulo, limite=5)
                           if m["estado"] not in ("revogado", "substituido")), None)
        if achada:
            mid = achada["id"]
        else:
            mid = self.memoria.criar(self.principal, MemoriaIn(
                tipo="estrutural", titulo=titulo[:200], resumo=conteudo.splitlines()[0][:300], conteudo=conteudo, namespace=ns,
                tags=tags[:15], fonte=FonteIn(tipo="documento"), confianca=0.4), "forja:alimentacao")["id"]
        if pai and pai != mid:
            try:
                self.grafo.ligar(self.principal, mid, pai, tipo_lig, ator="forja:alimentacao")
            except ErroDominio:
                pass
        return mid

    def _nota_projeto(self, d: LoteIn, pr: Projeto, raiz: Path, pai: str) -> str:
        rel = Path(pr.caminho).relative_to(raiz).as_posix() if Path(pr.caminho) != raiz else "."
        rotulo = "automação da empresa" if pr.escopo == "empresa" else "projeto próprio"
        linhas = [f"Projeto {pr.nome} ({rotulo}). {pr.readme}".strip(), "",
                  f"- Pasta: `{rel}`" + (f" (grupo {pr.grupo})" if pr.grupo else ""),
                  "- Linguagens: " + (", ".join(f"{k} ({v})" for k, v in list(pr.linguagens.items())[:5]) or "não identificadas"),
                  "- Estrutura: " + (", ".join(pr.estrutura) or "arquivos na raiz")]
        if pr.entradas:
            linhas.append("- Pontos de entrada: " + ", ".join(f"`{x}`" for x in pr.entradas))
        if pr.dependencias:
            linhas.append("- Dependências: " + ", ".join(pr.dependencias[:20]))
        linhas += ["", "Notas do estudo, entidades usadas e técnicas reutilizáveis ficam ligadas a esta nota."]
        tags = ["projeto", f"escopo-{pr.escopo}", pr.slug[:50], *[slug(k) for k in list(pr.linguagens)[:3]]]
        return self._hub(pr.namespace, f"Projeto: {pr.nome}", "\n".join(linhas), tags, pai)

    # ------------------------------------------------------------------ execucao em lote
    def estado(self) -> dict[str, Any]:
        with self.servico.repo.leitura() as t:
            linha = t.obter(T.Configuracao, CHAVE_ESTADO)
        e = dict((linha or {}).get("valor") or {"situacao": "parado", "projetos": []})
        e["rodando"] = bool(self._thread and self._thread.is_alive())
        return e

    def _salvar(self, e: dict[str, Any]) -> None:
        agora = iso(self.relogio.agora())
        with self.servico.repo.escrita() as t:
            linha = t.obter(T.Configuracao, CHAVE_ESTADO)
            if linha is None:
                t.inserir(T.Configuracao, id=CHAVE_ESTADO, valor=e, versao=1, atualizado_em=agora)
            else:
                t.atualizar(T.Configuracao, CHAVE_ESTADO, valor=e, versao=linha["versao"] + 1, atualizado_em=agora)

    def iniciar(self, d: LoteIn, esperar: bool = False) -> dict[str, Any]:
        with self._mu:
            if self._thread and self._thread.is_alive():
                raise ValidacaoDominio("Ja ha uma alimentacao em lote rodando; cancele ou espere terminar.")
            descoberta = self.descobrir(d)
            agora = iso(self.relogio.agora())
            e = {"situacao": "rodando", "inicio": agora, "fim": None, "raiz": descoberta["raiz"], "pedido": d.model_dump(),
                 "creditos": 0.0, "projetos": [{"nome": p["nome"], "slug": p["slug"], "escopo": p["escopo"], "namespace": p["namespace"],
                                                "caminho": p["caminho"], "etapa": "na_fila"} for p in descoberta["projetos"]],
                 "ignorados": len(descoberta["ignorados"])}
            self._salvar(e)
            self._parar.clear()
            self._thread = threading.Thread(target=self._rodar, args=(d, descoberta, e), name="forja-alimentacao", daemon=True)
            self._thread.start()
        if esperar:
            self._thread.join()
        return self.estado()

    def cancelar(self) -> dict[str, Any]:
        self._parar.set()
        return self.estado()

    def _creditos(self, tarefas: list[str]) -> float:
        if not tarefas:
            return 0.0
        total = 0.0
        with self.servico.repo.leitura() as t:
            for e in t.s.query(T.Execucao).filter(T.Execucao.tarefa_id.in_(tarefas)).all():
                consumo = ((e.resultado or {}).get("consumo") or {})
                c = consumo.get("creditos")
                total += float(c) if isinstance(c, (int, float)) else float(consumo.get("chamadas_modelo") or 0)
        return round(total, 4)

    def _situacao_tarefa(self, tarefa_id: str) -> str:
        with self.servico.repo.leitura() as t:
            tarefa = t.obter(T.Tarefa, tarefa_id)
        return tarefa["estado"] if tarefa else "falhou"

    def _rodar(self, d: LoteIn, descoberta: dict[str, Any], e: dict[str, Any]) -> None:
        try:
            self._executar(d, descoberta, e)
            e["situacao"] = "cancelado" if self._parar.is_set() else "concluido"
        except Exception as erro:  # noqa: BLE001 - o lote registra a falha e para; nunca derruba o servidor
            log.exception("alimentacao em lote falhou")
            e["situacao"], e["erro"] = "falhou", str(erro)[:300]
        e["fim"] = iso(self.relogio.agora())
        self._salvar(e)

    def _executar(self, d: LoteIn, descoberta: dict[str, Any], e: dict[str, Any]) -> None:
        raiz = Path(descoberta["raiz"])
        pol = self.politica() if self.politica else None
        indices = {esc: self._hub(self.namespace(d, esc), f"Projetos: {'empresa ' + d.empresa_id if esc == 'empresa' else 'próprios'}",
                                  ("Índice das automações e sistemas da empresa." if esc == "empresa" else "Índice dos projetos próprios.")
                                  + " Cada projeto é uma subpasta; entidades compartilhadas ficam em 'entidades'.",
                                  ["indice", "topico", f"escopo-{esc}"], None)
                   for esc in sorted({p["escopo"] for p in descoberta["projetos"]})}
        grupos: dict[tuple[str, str], str] = {}
        projetos = [Projeto(**p) for p in descoberta["projetos"]]
        hubs: dict[str, str] = {}
        for i, pr in enumerate(projetos):  # 1) deterministico: indice de codigo + nota-hub (rapido, sem creditos)
            if self._parar.is_set():
                return
            item = e["projetos"][i]
            pai = indices[pr.escopo]
            if pr.grupo:
                chave = (pr.escopo, pr.grupo)
                if chave not in grupos:
                    grupos[chave] = self._hub(self.namespace(d, pr.escopo, slug(pr.grupo)), f"Grupo: {pr.grupo}",
                                              f"Grupo de projetos {pr.grupo}: partes do mesmo sistema (ex.: front, back, admin).",
                                              ["grupo", "topico", f"escopo-{pr.escopo}"], pai)
                pai = grupos[chave]
            hubs[pr.slug] = self._nota_projeto(d, pr, raiz, pai)
            item["hub"] = hubs[pr.slug]
            if d.indexar:
                try:
                    with aplicar(pol) if pol is not None else _nulo():
                        r = self.memoria.ingerir_diretorio(self.principal, IngerirIn(namespace=pr.namespace, raiz=pr.caminho,
                                                                                     repositorio=pr.slug[:200], extensoes=EXTENSOES))
                    item["indice"] = {k: r[k] for k in ("novos", "alterados", "inalterados", "ignorados")}
                except ErroDominio as erro:
                    item["indice"] = {"erro": str(erro)[:200]}
            item["etapa"] = "indexado"
            self._salvar(e)
        if not d.estudar:
            return
        ativos: dict[int, tuple[str, float]] = {}  # indice do projeto -> (tarefa_id, inicio)
        tarefas: list[str] = []
        fila = list(range(len(projetos)))
        while (fila or ativos) and not self._parar.is_set():
            for i, (tid, t0) in list(ativos.items()):  # 2) estudos com IA, N por vez
                situacao = self._situacao_tarefa(tid)
                # bloqueada = parou e espera o usuario (laco, orcamento, seguranca): libera a vaga; o estudo fica no quadro
                if situacao in ("concluida", "falhou", "cancelada", "expirada", "bloqueada") or time.monotonic() - t0 > self.espera_max_s:
                    e["projetos"][i]["etapa"] = "estudado" if situacao == "concluida" else f"estudo_{situacao}"
                    ativos.pop(i)
                    if situacao == "concluida":
                        self._marcar_estudado(hubs.get(projetos[i].slug))
            e["creditos"] = self._creditos(tarefas)
            teto = d.teto_creditos > 0 and e["creditos"] >= d.teto_creditos
            while fila and len(ativos) < d.paralelo and not teto and not self._parar.is_set():
                i = fila.pop(0)
                pr = projetos[i]
                if not d.reestudar and self._ja_estudado(hubs.get(pr.slug)):
                    e["projetos"][i]["etapa"] = "ja_estudado"
                    continue
                try:
                    r = self._estudar(d, pr, hubs[pr.slug])
                    ativos[i] = (r["tarefa"]["id"], time.monotonic())
                    tarefas.append(r["tarefa"]["id"])
                    e["projetos"][i].update(etapa="estudando", tarefa_id=r["tarefa"]["id"])
                except ErroDominio as erro:
                    e["projetos"][i].update(etapa="estudo_recusado", erro=str(erro)[:200])
            if teto and fila:
                for i in fila:
                    e["projetos"][i]["etapa"] = "teto_de_creditos"
                fila = []
                e["teto_atingido"] = True
            self._salvar(e)
            if ativos:
                self._parar.wait(self.intervalo)
        e["creditos"] = self._creditos(tarefas)

    def _ja_estudado(self, hub: str | None) -> bool:
        if not hub:
            return False
        with self.memoria.repo.leitura() as t:
            m = t.obter(T.Memoria, hub)
        return bool(m and "estudado" in (m["tags"] or []))

    def _marcar_estudado(self, hub: str | None) -> None:
        if not hub:
            return
        from forja.memoria.contratos import MemoriaAtualizaIn

        try:
            m = self.memoria.obter(self.principal, hub)
            if "estudado" not in (m["tags"] or []):
                self.memoria.atualizar(self.principal, hub, MemoriaAtualizaIn(expected_version=m["versao"], tags=[*(m["tags"] or []), "estudado"][:30],
                                                                          motivo="estudo do projeto concluido"), "forja:alimentacao")
        except ErroDominio:
            pass

    def _estudar(self, d: LoteIn, pr: Projeto, hub: str) -> dict[str, Any]:
        from forja.orquestracao.estudos import EstudoIn

        rotulo = "automacao da EMPRESA" if pr.escopo == "empresa" else "projeto PROPRIO do usuario"
        pedido = (
            f"Estude o projeto '{pr.nome}' (pasta de consulta, somente leitura; provavel {rotulo}) para o segundo cerebro do usuario. "
            "Leia so o necessario: README/docs, pontos de entrada, modulos centrais e configuracao de EXEMPLO. NAO abra as pastas "
            + ", ".join(IGNORAR_AGENTE[:9]) + " nem .env/chaves; nunca copie dados de clientes (CPF, contas, nomes), tokens ou URLs com "
            "credencial. Escreva de 4 a 12 notas: (1) 'Projeto " + pr.nome + ": visao geral' (proposito, fluxo principal, entradas e "
            "saidas, como rodar e testar) com a linha 'Classificacao: automacao empresarial | automacao generica | projeto pessoal' e o "
            "motivo; (2) arquitetura, fluxos e regras DESTE projeto (Escopo: projeto); (3) cada sistema externo, orgao, API interna ou "
            "regra de negocio que outros projetos tambem usam vira nota Escopo: entidade com 'Entidade: <nome>' - antes, busque com "
            "forja_buscar_memoria; se a nota da entidade ja existir, use o MESMO titulo e escreva so o que e novo; (4) tecnicas "
            "reutilizaveis (retry, login, leitura de PDF...) como Escopo: generico. Fatos abaixo sao da Forja (deterministicos)."
        )
        if d.foco:
            pedido += f" Foco do usuario: {d.foco}."
        extras = {"pedido": pedido, "raiz_id": hub, "ns_entidade": f"{self.namespace(d, pr.escopo)}/entidades",
                  "ns_generico": "pessoal/geral", "ignorar": IGNORAR_AGENTE, "projeto_nome": pr.nome, "lote": True}
        return self.estudos.solicitar(EstudoIn(tipo="pasta", alvo=pr.caminho, namespace=pr.namespace, pesquisar_web=False, executar=True),
                                      extras)


class _nulo:  # noqa: N801 - context manager vazio
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_: object) -> None:
        return None
