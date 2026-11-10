"""4.8/4.9: precisao da busca em linguagem natural sobre um corpus REAL de codigo, sem rotulagem manual (metodo CodeSearchNet).

Como funciona: cada funcao/classe Python com docstring vira um caso; a 1a frase da docstring e a PERGUNTA e o arquivo da funcao e a
resposta certa. As docstrings sao REMOVIDAS da copia indexada (senao a busca acharia o proprio texto e a medida seria inutil).
Compara: baseline lexical x busca atual (radicais/sinonimos) x, opcionalmente, embeddings locais (fastembed) e hibrido (RRF).

Privacidade: le so a raiz informada (pastas permitidas da Forja), copia para um diretorio TEMPORARIO fora do repositorio, usa um banco
temporario e apaga tudo no fim. Imprime apenas numeros agregados (nenhum caminho, nome ou trecho do corpus).

Uso: python scripts/avaliar_busca_codigo.py --raiz "C:\\...\\codigos" [--amostra 300] [--k 5] [--embeddings] [--json saida.json]
"""

from __future__ import annotations

import argparse
import ast
import json
import random
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forja.memoria.avaliacao import Caso, avaliar  # noqa: E402

IGNORAR = {".git", ".venv", "venv", "env", "node_modules", "site-packages", "__pycache__", ".worktrees", "dist", "build", ".tox", ".mypy_cache"}
MIN_PALAVRAS = 5
RRF_K = 60
NS = "empresa/avaliacao"  # corpus real tratado como dado de empresa (nunca publico), mesmo sendo temporario


def _arquivos(raiz: Path) -> list[Path]:
    from forja.seguranca.acoes import caminho_sensivel

    saida = []
    for p in raiz.rglob("*.py"):
        partes = set(p.relative_to(raiz).parts[:-1])
        if partes & IGNORAR or caminho_sensivel(str(p)) or p.stat().st_size > 400_000:
            continue
        saida.append(p)
    return sorted(saida)


def _sem_docstrings(fonte: str) -> tuple[str, list[tuple[str, str]]]:
    """(codigo sem docstrings, [(simbolo, 1a frase da docstring)])."""
    arvore = ast.parse(fonte)
    casos = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Module):
            corpo = getattr(no, "body", [])
            if corpo and isinstance(corpo[0], ast.Expr) and isinstance(getattr(corpo[0], "value", None), ast.Constant) and isinstance(corpo[0].value.value, str):
                doc = corpo[0].value.value
                frase = re.split(r"(?<=[.!?])\s|\n\s*\n", doc.strip(), maxsplit=1)[0]
                frase = " ".join(frase.split())[:200]
                if not isinstance(no, ast.Module) and len(frase.split()) >= MIN_PALAVRAS:
                    casos.append((getattr(no, "name", "?"), frase))
                corpo[0] = ast.Pass() if len(corpo) == 1 else corpo[0]
                if len(corpo) > 1:
                    del corpo[0]
    return ast.unparse(arvore), casos


def _idioma(txt: str) -> str:
    pt = len(re.findall(r"\b(de|do|da|para|com|que|uma|um|os|as|nao|não|e|em|por|se)\b", txt.lower()))
    en = len(re.findall(r"\b(the|of|to|and|for|with|is|a|an|in|returns?|this|that|from)\b", txt.lower()))
    return "pt" if pt >= en else "en"


def preparar(raiz: Path, destino: Path, amostra: int, semente: int) -> tuple[list[Caso], dict[str, str]]:
    casos: list[Caso] = []
    textos: dict[str, str] = {}
    for p in _arquivos(raiz):
        try:
            limpo, docs = _sem_docstrings(p.read_text(encoding="utf-8", errors="strict"))
        except (SyntaxError, UnicodeDecodeError, ValueError, RecursionError):
            continue
        rel = p.relative_to(raiz).as_posix()
        alvo = destino / rel
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(limpo, encoding="utf-8")
        textos[rel] = limpo
        casos += [Caso(frase, frozenset({rel}), _idioma(frase)) for _sim, frase in docs]
    import hashlib

    copias: dict[str, set[str]] = {}  # arquivos com conteudo identico (copias entre projetos) contam como a mesma resposta certa
    for rel, txt in textos.items():
        copias.setdefault(hashlib.sha256(txt.encode()).hexdigest(), set()).add(rel)
    de_rel = {rel: frozenset(g) for g in copias.values() for rel in g}
    casos = [Caso(c.consulta, de_rel[next(iter(c.relevantes))], c.categoria) for c in casos]
    vistos, unicos = set(), []
    for c in casos:  # perguntas repetidas (docstrings copiadas) nao valem como casos distintos
        if c.consulta.casefold() not in vistos:
            vistos.add(c.consulta.casefold())
            unicos.append(c)
    random.Random(semente).shuffle(unicos)
    return unicos[:amostra], textos


def _embeddings(textos: dict[str, str], casos: list[Caso], modelo: str):
    import numpy as np
    from fastembed import TextEmbedding  # dependencia OPCIONAL (so para o experimento 4.9)

    emb = TextEmbedding(model_name=modelo)
    blocos, dono = [], []
    for rel, txt in textos.items():  # janelas de ~40 linhas: embeddings de arquivos inteiros perdem o detalhe
        linhas = txt.splitlines()
        for i in range(0, max(1, len(linhas)), 30):
            blocos.append(f"{rel}\n" + "\n".join(linhas[i:i + 40])[:2000])
            dono.append(rel)
    t0 = time.perf_counter()
    m = np.array(list(emb.embed(blocos, batch_size=64)), dtype="float32")
    t_indice = time.perf_counter() - t0
    m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
    q = np.array(list(emb.query_embed([c.consulta for c in casos])), dtype="float32")
    q /= np.linalg.norm(q, axis=1, keepdims=True) + 1e-9
    por_consulta = {}
    for c, vq in zip(casos, q, strict=True):
        notas = m @ vq
        ordem, vistos = [], set()
        for i in np.argsort(-notas):
            if dono[i] not in vistos:
                vistos.add(dono[i])
                ordem.append(dono[i])
            if len(ordem) >= 10:
                break
        por_consulta[c.consulta] = ordem
    return por_consulta, {"blocos": len(blocos), "segundos_indice": round(t_indice, 1), "modelo": modelo}


def _rrf(*rankings: list[str]) -> list[str]:
    nota: dict[str, float] = {}
    for r in rankings:
        for pos, i in enumerate(r, start=1):
            nota[i] = nota.get(i, 0.0) + 1.0 / (RRF_K + pos)
    return sorted(nota, key=lambda i: -nota[i])[:10]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raiz", required=True)
    ap.add_argument("--amostra", type=int, default=300)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--semente", type=int, default=7)
    ap.add_argument("--embeddings", action="store_true")
    ap.add_argument("--modelo", default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    ap.add_argument("--json", default="")
    ap.add_argument("--glossario", action="store_true", help="mede COM a extensao knowledge/ontologias/sinonimos.json (comparacao)")
    a = ap.parse_args()
    from forja.adapters.sqlite.banco import criar_engines, migrar
    from forja.adapters.sqlite.repositorio import RepositorioSqlite
    from forja.memoria.contratos import IngerirIn
    from forja.memoria.modelo import Principal
    from forja.orquestracao.memoria_servico import ServicoMemoria

    tmp = Path(tempfile.mkdtemp(prefix="forja-aval-"))
    try:
        copia = tmp / "corpus"
        t0 = time.perf_counter()
        casos, textos = preparar(Path(a.raiz), copia, a.amostra, a.semente)
        db = tmp / "aval.sqlite3"
        migrar(db)
        w, r = criar_engines(db)
        repo = RepositorioSqlite(w, r)
        p = Principal("avaliacao", frozenset({NS}))
        from forja.memoria.linguagem import caminho_sinonimos

        s = ServicoMemoria(repo, raizes_ingestao=[copia], sinonimos=caminho_sinonimos() if a.glossario else None)
        ing = s.ingerir_diretorio(p, IngerirIn(namespace=NS, raiz=str(copia), repositorio="corpus", extensoes=[".py"]))
        t_ing = time.perf_counter() - t0

        sinais: dict[str, tuple[float, bool, float]] = {}  # consulta -> (cobertura do 1o, sem correspondencia exata, margem 1o-2o)

        def lexical(expandir: bool):
            def f(q: str) -> list[str]:
                try:
                    res = s.buscar(p, q, [NS], fontes=("codigo",), limite=10, expandir=expandir)
                except Exception:  # noqa: BLE001 - consulta sem termos uteis: zero acertos
                    sinais[q] = (0.0, True, 0.0)
                    return []
                if expandir:
                    rs = res["resultados"]
                    top = rs[0].get("cobertura", 1.0) if rs else 0.0
                    margem = (rs[0].get("pontuacao", 0) - rs[1].get("pontuacao", 0)) / max(rs[0].get("pontuacao", 0), 1e-9) if len(rs) > 1 else (1.0 if rs else 0.0)
                    sinais[q] = (float(top), any("sem correspondencia exata" in a for a in res.get("avisos", [])), float(margem))
                return list(dict.fromkeys(i["caminho"] for i in res["resultados"]))
            return f

        t1 = time.perf_counter()
        base, nova = lexical(False), lexical(True)
        ranks_nova = {c.consulta: nova(c.consulta) for c in casos}
        latencia = (time.perf_counter() - t1) / max(1, len(casos)) * 1000
        resultado = {"casos": len(casos), "arquivos": len(textos), "ingestao": {**ing, "segundos": round(t_ing, 1)},
                     "baseline": avaliar(base, casos, a.k), "nova": avaliar(lambda q: ranks_nova[q], casos, a.k),
                     "latencia_ms_por_consulta": round(latencia, 1)}
        if a.embeddings:
            ranks_emb, info = _embeddings(textos, casos, a.modelo)
            resultado["embeddings"] = {**avaliar(lambda q: ranks_emb[q], casos, a.k), "info": info}
            resultado["hibrido_rrf"] = avaliar(lambda q: _rrf(ranks_nova[q], ranks_emb[q]), casos, a.k)
            # Fallback (proposta do usuario): busca atual primeiro; so quando ela parece fraca, recorre ao hibrido.
            gatilhos = {f"cobertura<{lim}": (lambda q, lim=lim: (not ranks_nova[q]) or sinais[q][0] < lim) for lim in (0.4, 0.6, 0.8)}
            gatilhos |= {f"margem<{m}": (lambda q, m=m: (not ranks_nova[q]) or sinais[q][2] < m) for m in (0.05, 0.15, 0.3)}
            gatilhos["vazio"] = lambda q: not ranks_nova[q]
            for limiar, gatilho in gatilhos.items():
                acionadas = sum(1 for c in casos if gatilho(c.consulta))
                resultado[f"fallback_{limiar}"] = {**avaliar(lambda q, g=gatilho: _rrf(ranks_nova[q], ranks_emb[q]) if g(q) else ranks_nova[q], casos, a.k),
                                                     "acionado_em": round(acionadas / max(1, len(casos)), 3)}
        repo.fechar()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # a copia do corpus nunca fica para tras

    k = a.k
    fmt = lambda m: f"{m[f'recall@{k}']:.3f} / {m['mrr']:.3f} / {m[f'ndcg@{k}']:.3f}"  # noqa: E731
    print(f"casos={resultado['casos']} arquivos={resultado['arquivos']} latencia={resultado['latencia_ms_por_consulta']} ms/consulta")
    print(f"{'':14}recall@{k} / MRR / nDCG@{k}")
    for nome in ("baseline", "nova", "embeddings", "hibrido_rrf", *[k for k in resultado if k.startswith("fallback_")]):
        if nome in resultado:
            m = resultado[nome]
            extra = f" (hibrido em {m['acionado_em']:.0%} das consultas)" if "acionado_em" in m else ""
            print(f"{nome:14}{fmt(m['global'])}{extra}   " + "  ".join(f"{c}: {fmt(v)} (n={v['casos']})" for c, v in m["por_categoria"].items()))
    if "embeddings" in resultado:
        print("embeddings:", resultado["embeddings"]["info"])
    if a.json:
        Path(a.json).write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
