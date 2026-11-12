"""codigo.estrutura: indice ESTRUTURAL do codigo (sem embeddings): definicoes, referencias, dependencias e mapa ranqueado.

Por que (pesquisa 2026, arXiv 2606.22417): um mapa de simbolos/imports/chamadas melhora a localizacao em mudancas que cruzam
varios arquivos, sem o custo de um modelo vetorial. E o "repo map" usado por agentes de codigo, em versao deterministica.

- Python: AST (definicoes com linha/fim/assinatura, imports resolvidos para arquivos do projeto, chamadas por nome).
- JS/TS: regex leve (definicoes, `import ... from`/`require`, chamadas `nome(`); demais linguagens: so definicoes.
- Incremental: cada arquivo e analisado UMA vez por (tamanho, mtime); mudou, reanalisa so ele. Cache em memoria do processo.
- Seguranca: mesma varredura do indexador (sem links, sem segredos, sem pastas proibidas); trechos passam pela redacao do contrato.
"""

from __future__ import annotations

import ast
import os
import re
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from forja.dominio.erros import ValidacaoDominio
from forja.ferramentas.caminhos import resolver_dentro
from forja.ferramentas.contrato import ResultadoFerramenta, montar, tokens_de_bytes
from forja.memoria.indexador import LINGUAGENS, MAX_BYTES, eh_minificado, extrair_simbolos_generico, listar_arquivos

MAX_ARQUIVOS = 5000
MAX_CACHE = 50_000
OPERACOES = ("mapa", "definicao", "referencias", "dependencias", "impacto", "testes_afetados", "funcao", "grafo")
_JS_IMPORT = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)["']([^"'\n]+)["']""")
_JS_CHAMADA = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(")
_JS_RESERVADAS = frozenset("if for while switch catch function return typeof new await async super import require class".split())
_EXT_JS = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")


@dataclass(frozen=True)
class Definicao:
    nome: str  # "Classe.metodo" para metodos
    tipo: str
    linha: int
    fim: int
    assinatura: str = ""

    @property
    def final(self) -> str:
        return self.nome.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class Funcao:
    """No do GRAFO DE FUNCOES: o que a funcao exige (parametros/tipos), o que devolve, o que levanta e onde mora."""
    nome: str
    tipo: str
    linha: int
    fim: int
    parametros: tuple[tuple[str, str, str], ...] = ()  # (nome, anotacao, padrao)
    retorno: str = ""
    doc: str = ""
    decoradores: tuple[str, ...] = ()
    levanta: tuple[str, ...] = ()
    assincrona: bool = False

    def assinatura(self) -> str:
        ps = []
        for n, an, pd in self.parametros:
            ps.append(n + (f": {an}" if an else "") + (f" = {pd}" if pd else ""))
        return f"{'async ' if self.assincrona else ''}{self.nome}({', '.join(ps)})" + (f" -> {self.retorno}" if self.retorno else "")


@dataclass
class Analise:
    linguagem: str
    definicoes: list[Definicao] = field(default_factory=list)
    imports: list[tuple[str, int]] = field(default_factory=list)  # (modulo ou caminho como escrito, linha)
    chamadas: list[tuple[str, int]] = field(default_factory=list)  # (nome final chamado, linha)
    erro: str | None = None
    funcoes: dict[str, Funcao] = field(default_factory=dict)  # nome qualificado -> no do grafo
    # (chamador qualificado | '<modulo>', chamado, linha, forma): forma 'n' = nome solto f(), 's' = self.f(), 'a' = obj.f()
    arestas: list[tuple[str, str, int, str]] = field(default_factory=list)


_cache: dict[str, tuple[int, int, Analise]] = {}
_mu = threading.Lock()
MAX_TXT = 80


def _txt(no: ast.AST | None) -> str:
    if no is None:
        return ""
    try:
        s = ast.unparse(no)
    except Exception:  # noqa: BLE001 - expressao exotica nao derruba a analise
        return ""
    return s if len(s) <= MAX_TXT else s[: MAX_TXT - 1] + "…"


def _parametros(f: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[tuple[str, str, str], ...]:
    a = f.args
    posicionais = [*a.posonlyargs, *a.args]
    padroes = [None] * (len(posicionais) - len(a.defaults)) + list(a.defaults)
    saida = [(x.arg, _txt(x.annotation), _txt(d)) for x, d in zip(posicionais, padroes, strict=True)]
    if a.vararg:
        saida.append((f"*{a.vararg.arg}", _txt(a.vararg.annotation), ""))
    saida += [(x.arg, _txt(x.annotation), _txt(d)) for x, d in zip(a.kwonlyargs, a.kw_defaults, strict=True)]
    if a.kwarg:
        saida.append((f"**{a.kwarg.arg}", _txt(a.kwarg.annotation), ""))
    return tuple(p for p in saida if p[0] not in ("self", "cls"))


def _analisar_python(texto: str, rel: str) -> Analise:
    a = Analise("python")
    arvore = ast.parse(texto)
    pacote = rel.rsplit("/", 1)[0].replace("/", ".") if "/" in rel else ""
    atual: list[str] = []  # pilha da funcao em que estamos (para atribuir cada chamada ao seu chamador)

    def visitar(no: ast.AST, classe: str | None) -> None:
        for f in ast.iter_child_nodes(no):
            if isinstance(f, ast.ClassDef):
                a.definicoes.append(Definicao(f.name, "classe", f.lineno, getattr(f, "end_lineno", f.lineno) or f.lineno))
                visitar(f, f.name)
            elif isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef):
                args = ", ".join(x.arg for x in f.args.args)
                nome = f"{classe}.{f.name}" if classe else f.name
                fim = getattr(f, "end_lineno", f.lineno) or f.lineno
                a.definicoes.append(Definicao(nome, "metodo" if classe else "funcao", f.lineno, fim, f"({args})"))
                levanta = sorted({_txt(x.exc.func if isinstance(x.exc, ast.Call) else x.exc).split("(")[0]
                                  for x in ast.walk(f) if isinstance(x, ast.Raise) and x.exc is not None})
                doc = (ast.get_docstring(f) or "").strip().splitlines()
                a.funcoes[nome] = Funcao(nome, "metodo" if classe else "funcao", f.lineno, fim, _parametros(f), _txt(f.returns),
                                         (doc[0][:160] if doc else ""), tuple(_txt(d) for d in f.decorator_list),
                                         tuple(x for x in levanta if x)[:8], isinstance(f, ast.AsyncFunctionDef))
                atual.append(nome)
                visitar(f, classe)
                atual.pop()
            elif isinstance(f, ast.Import):
                a.imports += [(x.name, f.lineno) for x in f.names]
            elif isinstance(f, ast.ImportFrom):
                base = f.module or ""
                if f.level:  # import relativo: resolve contra o pacote do arquivo
                    partes = pacote.split(".") if pacote else []
                    partes = partes[: len(partes) - (f.level - 1)] if f.level > 1 else partes
                    base = ".".join([*partes, base] if base else partes)
                a.imports.append((base, f.lineno))
                a.imports += [(f"{base}.{x.name}" if base else x.name, f.lineno) for x in f.names if x.name != "*"]
                a.chamadas += [(x.name, f.lineno) for x in f.names if x.name != "*"]  # importar um nome tambem e referencia
            elif isinstance(f, ast.Call):
                fn = f.func
                nome = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
                if nome:
                    a.chamadas.append((nome, f.lineno))
                    forma = "n" if isinstance(fn, ast.Name) else (
                        "s" if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id in ("self", "cls") else "a")
                    a.arestas.append((atual[-1] if atual else "<modulo>", nome, f.lineno, forma))
                visitar(f, classe)
            else:
                visitar(f, classe)

    visitar(arvore, None)
    return a


def _analisar_js(texto: str, ling: str) -> Analise:
    a = Analise(ling)
    a.definicoes = [Definicao(s.nome, s.tipo, s.linha, s.linha) for s in extrair_simbolos_generico(ling, texto)]
    funcs = sorted((d.linha, d.nome) for d in a.definicoes if d.tipo == "funcao")
    for d in a.definicoes:
        if d.tipo == "funcao":
            a.funcoes[d.nome] = Funcao(d.nome, "funcao", d.linha, d.linha)
    for n, linha in enumerate(texto.splitlines(), start=1):
        if len(linha) > 2000:
            continue
        a.imports += [(m.group(1), n) for m in _JS_IMPORT.finditer(linha)]
        novos = [(m.group(1), n) for m in _JS_CHAMADA.finditer(linha) if m.group(1) not in _JS_RESERVADAS]
        a.chamadas += novos
        # chamador aproximado: a funcao declarada mais recente acima da linha (regex nao sabe onde a funcao termina)
        dono = next((nm for ln, nm in reversed(funcs) if ln <= n), "<modulo>")
        a.arestas += [(dono, nome, ln, "n") for nome, ln in novos if not (nome == dono and ln == a.funcoes.get(dono, Funcao("", "", 0, 0)).linha)]
    return a


def analisar_arquivo(p: Path, rel: str) -> Analise | None:
    try:
        st = p.stat()
    except OSError:
        return None
    chave = str(p)
    with _mu:
        hit = _cache.get(chave)
    if hit and hit[0] == st.st_size and hit[1] == st.st_mtime_ns:
        return hit[2]
    try:
        dados = p.read_bytes()
    except OSError:
        return None
    if b"\x00" in dados[:8192] or len(dados) > MAX_BYTES:
        return None
    texto = dados.decode("utf-8", errors="replace")
    if eh_minificado(p.name, texto):
        return None
    ling = LINGUAGENS.get(p.suffix.lower(), "texto")
    try:
        if ling == "python":
            an = _analisar_python(texto, rel)
        elif ling in ("javascript", "typescript"):
            an = _analisar_js(texto, ling)
        else:
            an = Analise(ling, [Definicao(s.nome, s.tipo, s.linha, s.linha) for s in extrair_simbolos_generico(ling, texto)])
    except (SyntaxError, ValueError, RecursionError) as e:  # arquivo invalido nunca derruba o indice
        an = Analise(ling, erro=f"{type(e).__name__}")
    with _mu:
        if len(_cache) >= MAX_CACHE:
            _cache.clear()
        _cache[chave] = (st.st_size, st.st_mtime_ns, an)
    return an


@dataclass
class Indice:
    raiz: Path
    arquivos: dict[str, Analise]
    truncado: bool
    bytes_total: int
    _modulos: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for rel in self.arquivos:
            if rel.endswith(".py"):
                mod = rel[:-3].replace("/", ".")
                if mod.endswith(".__init__"):
                    mod = mod[: -len(".__init__")]
                self._modulos[mod] = rel
                if mod.startswith("src."):  # layout src/: 'src.pacote.x' tambem responde por 'pacote.x'
                    self._modulos.setdefault(mod.split(".", 1)[1], rel)

    def origem_de(self, rel: str, nome: str) -> str | None:
        """Arquivo de onde `rel` importou `nome` (`from pacote.mod import nome`), se for do projeto."""
        an = self.arquivos.get(rel)
        if an is None:
            return None
        for mod, _l in an.imports:
            if mod.endswith("." + nome):
                destino = self.resolver_import(rel, mod[: -len(nome) - 1])
                if destino:
                    return destino
        return None

    def resolver_import(self, origem: str, alvo: str) -> str | None:
        """Arquivo do projeto que um import aponta (ou None se for externo)."""
        if origem.endswith(".py"):
            return self._modulos.get(alvo)
        if alvo.startswith("."):
            base = (self.raiz / origem).parent / alvo
            for cand in [base, *[base.with_suffix(e) for e in _EXT_JS], *[base / f"index{e}" for e in _EXT_JS]]:
                try:
                    rel = cand.resolve().relative_to(self.raiz.resolve()).as_posix()
                except (OSError, ValueError):
                    continue
                if rel in self.arquivos:
                    return rel
        return None

    def dependencias(self) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
        saem: dict[str, set[str]] = defaultdict(set)
        entram: dict[str, set[str]] = defaultdict(set)
        for rel, an in self.arquivos.items():
            for mod, _l in an.imports:
                destino = self.resolver_import(rel, mod)
                if destino and destino != rel:
                    saem[rel].add(destino)
                    entram[destino].add(rel)
        return saem, entram


def construir(raiz: Path, caminho: str = ".") -> Indice:
    base = raiz.resolve()
    alvo = resolver_dentro(raiz, caminho, diretorio=True) if caminho not in ("", ".") else base
    arquivos: dict[str, Analise] = {}
    truncado, total = False, 0
    for p in listar_arquivos(alvo):
        if len(arquivos) >= MAX_ARQUIVOS:
            truncado = True
            break
        rel = p.resolve().relative_to(base).as_posix()
        an = analisar_arquivo(p, rel)
        if an is not None:
            arquivos[rel] = an
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return Indice(base, arquivos, truncado, total)


def _linha(raiz: Path, rel: str, n: int) -> str:
    try:
        with open(raiz / rel, encoding="utf-8", errors="replace") as f:
            for i, linha in enumerate(f, start=1):
                if i == n:
                    return " ".join(linha.split())[:160]
    except OSError:
        pass
    return ""


def _casa(d: Definicao, alvo: str) -> int:
    """3 = nome exato, 2 = componente final (metodo), 1 = sem diferenciar maiusculas."""
    if d.nome == alvo:
        return 3
    if d.final == alvo or d.nome.endswith("." + alvo):
        return 2
    if d.nome.casefold() == alvo.casefold() or d.final.casefold() == alvo.casefold():
        return 1
    return 0


def estrutura_codigo(raiz: Path, caminho: str = ".", operacao: str = "mapa", alvo: str = "", limite: int = 30) -> ResultadoFerramenta:
    if operacao not in OPERACOES:
        raise ValidacaoDominio(f"operacao invalida (use {', '.join(OPERACOES)})")
    if operacao not in ("mapa", "grafo") and not alvo.strip():
        raise ValidacaoDominio("informe 'alvo' (nome do simbolo ou caminho do arquivo)")
    idx = construir(raiz, caminho)
    alvo = alvo.strip()
    avisos = ["indice interrompido no limite de arquivos"] if idx.truncado else []
    origem = tokens_de_bytes(idx.bytes_total)
    if operacao == "definicao":
        achados = sorted(((_casa(d, alvo), rel, d) for rel, an in idx.arquivos.items() for d in an.definicoes if _casa(d, alvo)),
                         key=lambda x: (-x[0], x[1], x[2].linha))[:limite]
        linhas = [f"{rel}:{d.linha}-{d.fim} {d.tipo} {d.nome}{d.assinatura}" for _, rel, d in achados]
        dados = {"definicoes": [{"caminho": rel, "linha": d.linha, "fim": d.fim, "tipo": d.tipo, "nome": d.nome,
                                 "assinatura": d.assinatura} for _, rel, d in achados]}
        resumo = "\n".join(linhas) or f"nenhuma definicao de '{alvo}'"
        return montar("codigo.estrutura", "", resumo, dados, len(achados) >= limite, avisos, origem)
    if operacao == "referencias":
        final = alvo.rsplit(".", 1)[-1]
        refs = sorted((rel, ln) for rel, an in idx.arquivos.items() for nome, ln in an.chamadas if nome == final)
        refs = list(dict.fromkeys(refs))
        defs = {(rel, d.linha) for rel, an in idx.arquivos.items() for d in an.definicoes if d.final == final}
        refs = [r for r in refs if r not in defs]
        por_arquivo = Counter(rel for rel, _ in refs)
        mostradas = refs[:limite]
        dados = {"total": len(refs), "arquivos": dict(por_arquivo.most_common(50)),
                 "referencias": [{"caminho": rel, "linha": ln, "texto": _linha(idx.raiz, rel, ln)} for rel, ln in mostradas]}
        linhas = [f"{r['caminho']}:{r['linha']}: {r['texto']}" for r in dados["referencias"]]
        resumo = (f"{len(refs)} referencia(s) a '{final}' em {len(por_arquivo)} arquivo(s)\n" + "\n".join(linhas)) if refs \
            else f"nenhuma referencia a '{final}'"
        return montar("codigo.estrutura", "", resumo, dados, len(refs) > limite, avisos, origem)
    if operacao == "funcao":
        return _op_funcao(idx, alvo, limite, avisos, origem)
    if operacao == "grafo":
        g = grafo_funcoes(idx, alvo.replace("\\", "/").lstrip("./") if alvo else "", limite * 4)
        linhas = [f"{n['local']} {n['assinatura']}" + (f" -> chama: {', '.join(n['chama'][:6])}" if n["chama"] else "")
                  + (f" | usada por {n['usada_por']}" if n["usada_por"] else "") for n in g["nos"][:limite]]
        resumo = f"grafo de funcoes: {len(g['nos'])} funcao(oes), {len(g['arestas'])} chamada(s) internas\n" + "\n".join(linhas)
        return montar("codigo.estrutura", "", resumo, g, len(g["nos"]) > limite, avisos, origem)
    saem, entram = idx.dependencias()
    if operacao == "testes_afetados":
        alvos = [a.strip().replace("\\", "/").lstrip("./") for a in alvo.split(",") if a.strip()][:50]
        testes = _testes_afetados(idx, entram, alvos, limite)
        dados = {"alterados": alvos, "testes": testes}
        resumo = (f"{len(testes)} arquivo(s) de teste cobrem {', '.join(alvos)}:\n" + "\n".join(testes)) if testes \
            else "nenhum teste importa esses arquivos (rode a suite completa)"
        return montar("codigo.estrutura", "", resumo, dados, len(testes) >= limite, avisos, origem)
    if operacao == "impacto":
        final = alvo.rsplit(".", 1)[-1]
        definidos = sorted({rel for rel, an in idx.arquivos.items() for d in an.definicoes if d.final == final})
        usam = sorted({rel for rel, an in idx.arquivos.items() for nome, _l in an.chamadas if nome == final} - set(definidos))
        testes = _testes_afetados(idx, entram, definidos + usam, limite)
        dados = {"definido_em": definidos, "usado_em": usam[:limite], "testes": testes, "total_usos": len(usam)}
        resumo = (f"'{final}' definido em: {', '.join(definidos) or '-'}\nusado em {len(usam)} arquivo(s): {', '.join(usam[:limite]) or '-'}\n"
                  f"testes a rodar: {', '.join(testes) or 'nenhum direto (rode a suite)'}")
        return montar("codigo.estrutura", "", resumo, dados, len(usam) > limite, avisos, origem)
    if operacao == "dependencias":
        rel = alvo.replace("\\", "/").lstrip("./")
        if rel not in idx.arquivos:
            raise ValidacaoDominio("arquivo fora do indice (caminho relativo a raiz, sem segredos nem pastas ignoradas)")
        externos = sorted({(m.split(".")[0] if rel.endswith(".py") else m) for m, _ in idx.arquivos[rel].imports
                           if m and not m.startswith(".") and not idx.resolver_import(rel, m)
                           and not idx.resolver_import(rel, m.rsplit(".", 1)[0])})[:limite]
        dados = {"importa": sorted(saem.get(rel, set())), "importado_por": sorted(entram.get(rel, set())), "externos": externos}
        resumo = (f"{rel} importa: {', '.join(dados['importa']) or '-'}\nimportado por: {', '.join(dados['importado_por']) or '-'}\n"
                  f"externos: {', '.join(externos) or '-'}")
        return montar("codigo.estrutura", "", resumo, dados, False, avisos, origem)
    # mapa: arquivos mais centrais primeiro (quantos arquivos dependem deles + quantas referencias recebem de fora)
    nomes_por_arquivo = {rel: {d.final for d in an.definicoes if d.tipo != "secao"} for rel, an in idx.arquivos.items()}
    dono: dict[str, set[str]] = defaultdict(set)
    for rel, nomes in nomes_por_arquivo.items():
        for n in nomes:
            dono[n].add(rel)
    usos: Counter[str] = Counter()
    for rel, an in idx.arquivos.items():
        for nome, _l in an.chamadas:
            donos = dono.get(nome)
            if donos and len(donos) <= 3:  # nomes muito comuns (get, run...) nao contam
                for d in donos - {rel}:
                    usos[d] += 1
    pontos = {rel: 3 * len(entram.get(rel, ())) + min(usos[rel], 50) * 0.5 for rel in idx.arquivos}
    ordem = sorted((r for r, an in idx.arquivos.items() if an.definicoes), key=lambda r: (-pontos[r], r))[:limite]
    linhas, itens = [], []
    for rel in ordem:
        defs = [d for d in idx.arquivos[rel].definicoes if d.tipo in ("classe", "funcao", "tabela", "view", "function")][:12]
        linhas.append(f"{rel} [{len(entram.get(rel, ()))} dependente(s)]: " + ", ".join(d.nome for d in defs))
        itens.append({"caminho": rel, "dependentes": len(entram.get(rel, ())), "referencias": usos[rel],
                      "definicoes": [{"nome": d.nome, "linha": d.linha} for d in defs]})
    dados = {"arquivos_indexados": len(idx.arquivos), "mapa": itens,
             "erros_de_analise": sorted(r for r, an in idx.arquivos.items() if an.erro)[:20]}
    resumo = f"{len(idx.arquivos)} arquivo(s) indexados; mais centrais primeiro:\n" + "\n".join(linhas)
    return montar("codigo.estrutura", "", resumo, dados, len(ordem) >= limite, avisos, origem)


# ---------------------------------------------------------------------------------------------------- grafo de funcoes
def _donos(idx: Indice) -> dict[str, list[tuple[str, Funcao]]]:
    donos: dict[str, list[tuple[str, Funcao]]] = defaultdict(list)
    for rel, an in idx.arquivos.items():
        for f in an.funcoes.values():
            donos[f.nome.rsplit(".", 1)[-1]].append((rel, f))
    return donos


# metodos de tipos embutidos/bibliotecas: `x.get()` quase nunca e a funcao `get` do projeto
COMUNS = frozenset("""get set json items keys values append extend insert pop remove clear copy update add discard sort index count
strip lstrip rstrip split rsplit join format replace lower upper startswith endswith encode decode read write close open run
exists is_file is_dir mkdir resolve relative_to glob rglob iterdir stat unlink rename setdefault fromkeys match search sub findall
finditer group groups start end submit result done cancel wait acquire release put put_nowait get_nowait send recv execute fetchall
fetchone commit rollback query filter first all scalar mappings fill click locator then catch push map forEach reduce some find
includes slice splice toString addEventListener removeEventListener querySelector querySelectorAll appendChild getAttribute setAttribute
dispatchEvent preventDefault log warning error info debug exception emit on off""".split())
_EXT_PY = (".py",)


def _familia(rel: str) -> str:
    return "py" if rel.endswith(_EXT_PY) else "js" if rel.endswith(_EXT_JS) else "outro"


def _resolver_chamada(idx: Indice, rel: str, chamador: str, nome: str, forma: str,
                      donos: dict[str, list[tuple[str, Funcao]]]) -> list[tuple[str, Funcao]]:
    """Para onde uma chamada aponta DENTRO do projeto (vazio = externa ou ambigua). Regras conservadoras:
    f() -> funcao de modulo; self.f() -> metodo da propria classe (ou da mesma pasta); obj.f() -> metodo unico e de nome nao comum."""
    cand = [(r, f) for r, f in donos.get(nome, []) if _familia(r) == _familia(rel)]
    if not cand:
        return []
    if forma == "n":
        cand = [(r, f) for r, f in cand if "." not in f.nome]
        local = [(r, f) for r, f in cand if r == rel]
        importado = idx.origem_de(rel, nome)
        if local:  # definida no proprio arquivo vence
            cand = local
        elif importado:  # `from modulo import nome`: aponta exatamente para o arquivo importado
            cand = [(r, f) for r, f in cand if r == importado]
    elif forma == "s":
        classe = chamador.rsplit(".", 1)[0] if "." in chamador else ""
        mesma = [(r, f) for r, f in cand if r == rel and f.nome == f"{classe}.{nome}"]
        cand = mesma or [(r, f) for r, f in cand if r == rel and "." in f.nome]
    else:
        if nome in COMUNS:
            return []
        cand = [(r, f) for r, f in cand if "." in f.nome]
        if len({r for r, _f in cand}) > 2:
            return []
    return cand if 0 < len({r for r, _f in cand}) <= 3 else []


def _eh_teste_rel(rel: str) -> bool:
    return _eh_teste(rel) or "/fakes/" in f"/{rel}" or rel.startswith(("tests/", "test/"))


def grafo_funcoes(idx: Indice, escopo: str = "", limite: int = 400) -> dict:
    """Nos = funcoes do projeto (assinatura, tipos, retorno, excecoes, doc); arestas = chamadas que resolvem para funcoes do
    PROPRIO projeto, com regras conservadoras (ver _resolver_chamada). Testes ficam fora do grafo, salvo se `escopo` apontar
    para eles. `escopo` = pasta ou arquivo relativo. Ordenado pelas mais usadas (entrada) primeiro."""
    donos = _donos(idx)
    incluir_testes = bool(escopo) and _eh_teste_rel(escopo.rstrip("/") + "/x.py")
    arestas: set[tuple[str, str]] = set()
    for rel, an in idx.arquivos.items():
        if _eh_teste_rel(rel) and not incluir_testes:
            continue
        for chamador, nome, _l, forma in an.arestas:
            if chamador == "<modulo>":
                continue
            for r2, f2 in _resolver_chamada(idx, rel, chamador, nome, forma, donos):
                origem, destino = f"{rel}::{chamador}", f"{r2}::{f2.nome}"
                if origem != destino:
                    arestas.add((origem, destino))
    entrada = Counter(d for _o, d in arestas)
    saida: dict[str, list[str]] = defaultdict(list)
    for o, d in sorted(arestas):
        saida[o].append(d.split("::", 1)[1])
    nos = []
    for rel, an in idx.arquivos.items():
        if escopo and not (rel == escopo or rel.startswith(escopo.rstrip("/") + "/")):
            continue
        if _eh_teste_rel(rel) and not incluir_testes:
            continue
        for f in an.funcoes.values():
            chave = f"{rel}::{f.nome}"
            nos.append({"id": chave, "local": f"{rel}:{f.linha}-{f.fim}", "nome": f.nome, "assinatura": f.assinatura(),
                        "parametros": [{"nome": n, "tipo": t, "padrao": p} for n, t, p in f.parametros], "retorno": f.retorno,
                        "levanta": list(f.levanta), "doc": f.doc, "decoradores": list(f.decoradores),
                        "chama": sorted(set(saida.get(chave, [])))[:20], "usada_por": entrada.get(chave, 0)})
    nos.sort(key=lambda n: (-n["usada_por"], n["id"]))
    nos = nos[:limite]
    mantidos = {n["id"] for n in nos}
    return {"nos": nos, "arestas": [{"de": o, "para": d} for o, d in sorted(arestas) if o in mantidos and d in mantidos][: limite * 4],
            "escopo": escopo or "."}


def _op_funcao(idx: Indice, alvo: str, limite: int, avisos: list[str], origem: int) -> ResultadoFerramenta:
    """Tudo sobre uma funcao sem ler o arquivo: assinatura (o que exige), retorno, excecoes, doc, de onde vem (arquivo/linhas),
    o que ela chama (resolvido para o projeto) e quem a chama (arquivo:linha + funcao chamadora)."""
    final = alvo.rsplit(".", 1)[-1]
    donos = _donos(idx)
    achados = [(rel, f) for rel, f in donos.get(final, []) if f.nome == alvo or f.nome.endswith("." + alvo) or f.nome == final]
    if not achados:
        return montar("codigo.estrutura", "", f"nenhuma funcao '{alvo}' no indice", {"funcoes": []}, False, avisos, origem)
    itens, linhas = [], []
    for rel, f in achados[:5]:
        an = idx.arquivos[rel]
        chama = []
        for chamador, nome, ln, forma in an.arestas:
            if chamador != f.nome:
                continue
            alvos = _resolver_chamada(idx, rel, chamador, nome, forma, donos)
            chama.append({"nome": nome, "linha": ln, "definida_em": [f"{r}:{x.linha}" for r, x in alvos][:3] or ["externa"]})
        vistos: set[str] = set()
        chama = [c for c in chama if not (c["nome"] in vistos or vistos.add(c["nome"]))][:limite]
        chamadores = sorted({(r2, ln, ch) for r2, an2 in idx.arquivos.items() for ch, nome, ln, forma in an2.arestas
                             if nome == final and not (r2 == rel and ch == f.nome)
                             and any(r == rel and x.nome == f.nome for r, x in _resolver_chamada(idx, r2, ch, nome, forma, donos))})
        chamadores = sorted(chamadores, key=lambda c: (_eh_teste_rel(c[0]), c))[:limite]  # codigo de producao primeiro
        item = {"local": f"{rel}:{f.linha}-{f.fim}", "assinatura": f.assinatura(), "retorno": f.retorno, "levanta": list(f.levanta),
                "doc": f.doc, "decoradores": list(f.decoradores),
                "parametros": [{"nome": n, "tipo": t, "padrao": p} for n, t, p in f.parametros], "chama": chama,
                "chamada_por": [{"local": f"{r}:{ln}", "funcao": ch} for r, ln, ch in chamadores]}
        itens.append(item)
        linhas.append(f"{item['local']}  {item['assinatura']}" + (f"\n  doc: {f.doc}" if f.doc else "")
                      + (f"\n  levanta: {', '.join(f.levanta)}" if f.levanta else "")
                      + (f"\n  chama: {', '.join(c['nome'] + ('' if c['definida_em'] == ['externa'] else ' @' + c['definida_em'][0]) for c in chama)}" if chama else "")
                      + (f"\n  chamada por: {', '.join(c['funcao'] + ' @' + c['local'] for c in item['chamada_por'])}" if item["chamada_por"] else "\n  chamada por: (ninguem no projeto)"))
    return montar("codigo.estrutura", "", "\n".join(linhas), {"funcoes": itens}, len(achados) > 5, avisos, origem)


def resumo_grafo(raiz: Path, orcamento_tokens: int = 400) -> str:
    """Bloco CURTO para o prompt (preparacao de tarefas de codigo): as funcoes mais centrais com assinatura e ligacoes.
    O agente ve o mapa e so abre o que precisa; detalhes sob demanda via `codigo.estrutura` (funcao/grafo)."""
    idx = construir(raiz)
    g = grafo_funcoes(idx, "", 60)
    if not g["nos"]:
        return ""
    linhas = [f"\nGrafo de funcoes do projeto ({sum(len(a.funcoes) for a in idx.arquivos.values())} funcoes; as mais usadas):"]
    usado = len(linhas[0]) // 4
    for n in g["nos"]:
        linha = f"- {n['local']} {n['assinatura']}" + (f" -> {', '.join(n['chama'][:4])}" if n["chama"] else "")
        custo = len(linha) // 4 + 1
        if usado + custo > orcamento_tokens:
            break
        linhas.append(linha)
        usado += custo
    linhas.append("Detalhes (o que cada funcao exige, de onde vem, quem chama): ferramenta 'codigo.estrutura' operacao 'funcao' ou 'grafo'.\n")
    return "\n".join(linhas)


def limpar_cache() -> None:
    with _mu:
        _cache.clear()


def _eh_teste(r: str) -> bool:
    return "/tests/" in f"/{r}" or os.path.basename(r).startswith("test_") or r.endswith(
        ("_test.py", ".test.js", ".test.ts", ".spec.ts", ".spec.js"))


def arquivos_de_teste_afetados(raiz: Path, alterados: list[str], limite: int = 40) -> list[str]:
    """Testes que importam (direta ou transitivamente, 2 saltos) os arquivos alterados: base da verificacao direcionada."""
    idx = construir(raiz)
    _saem, entram = idx.dependencias()
    return _testes_afetados(idx, entram, alterados, limite)


def _testes_afetados(idx: Indice, entram: dict[str, set[str]], alterados: list[str], limite: int) -> list[str]:
    eh_teste = _eh_teste
    vistos, fronteira = set(alterados), list(alterados)
    for _ in range(2):
        prox = []
        for r in fronteira:
            for imp in entram.get(r, ()):
                if imp not in vistos:
                    vistos.add(imp)
                    prox.append(imp)
        fronteira = prox
    return sorted(r for r in vistos if eh_teste(r) and r in idx.arquivos)[:limite]
