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
OPERACOES = ("mapa", "definicao", "referencias", "dependencias", "impacto", "testes_afetados")
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


@dataclass
class Analise:
    linguagem: str
    definicoes: list[Definicao] = field(default_factory=list)
    imports: list[tuple[str, int]] = field(default_factory=list)  # (modulo ou caminho como escrito, linha)
    chamadas: list[tuple[str, int]] = field(default_factory=list)  # (nome final chamado, linha)
    erro: str | None = None


_cache: dict[str, tuple[int, int, Analise]] = {}
_mu = threading.Lock()


def _analisar_python(texto: str, rel: str) -> Analise:
    a = Analise("python")
    arvore = ast.parse(texto)
    pacote = rel.rsplit("/", 1)[0].replace("/", ".") if "/" in rel else ""

    def visitar(no: ast.AST, classe: str | None) -> None:
        for f in ast.iter_child_nodes(no):
            if isinstance(f, ast.ClassDef):
                a.definicoes.append(Definicao(f.name, "classe", f.lineno, getattr(f, "end_lineno", f.lineno) or f.lineno))
                visitar(f, f.name)
            elif isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef):
                args = ", ".join(x.arg for x in f.args.args)
                a.definicoes.append(Definicao(f"{classe}.{f.name}" if classe else f.name, "metodo" if classe else "funcao",
                                              f.lineno, getattr(f, "end_lineno", f.lineno) or f.lineno, f"({args})"))
                visitar(f, classe)
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
                visitar(f, classe)
            else:
                visitar(f, classe)

    visitar(arvore, None)
    return a


def _analisar_js(texto: str, ling: str) -> Analise:
    a = Analise(ling)
    a.definicoes = [Definicao(s.nome, s.tipo, s.linha, s.linha) for s in extrair_simbolos_generico(ling, texto)]
    for n, linha in enumerate(texto.splitlines(), start=1):
        if len(linha) > 2000:
            continue
        a.imports += [(m.group(1), n) for m in _JS_IMPORT.finditer(linha)]
        a.chamadas += [(m.group(1), n) for m in _JS_CHAMADA.finditer(linha) if m.group(1) not in _JS_RESERVADAS]
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
    if operacao != "mapa" and not alvo.strip():
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
