"""vault.indexar: estrutura de um cofre de notas Markdown (estilo Obsidian): links, backlinks, tags, orfas e quebrados."""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

from forja.ferramentas.caminhos import resolver_dentro
from forja.ferramentas.contrato import ResultadoFerramenta, montar, tokens_de_bytes
from forja.memoria.indexador import MAX_BYTES
from forja.memoria.wikilinks import extrair_tags, extrair_wikilinks
from forja.seguranca.acoes import caminho_sensivel
from forja.seguranca.pastas import proibido

MAX_NOTAS = 3000
IGNORAR = frozenset({".git", ".obsidian", ".trash", "node_modules", "__pycache__"})
TOPO = 8


def _frontmatter_tags(texto: str) -> list[str]:
    if not texto.startswith("---"):
        return []
    fim = texto.find("\n---", 3)
    if fim < 0:
        return []
    tags: list[str] = []
    em_lista = False
    for ln in texto[3:fim].splitlines():
        s = ln.strip()
        if s.lower().startswith("tags:"):
            resto = s[5:].strip().strip("[]")
            tags += [t.strip().strip("'\"#") for t in resto.split(",") if t.strip()]
            em_lista = not resto
        elif em_lista and s.startswith("- "):
            tags.append(s[2:].strip().strip("'\"#"))
        elif s:
            em_lista = False
    return [t for t in tags if t]


def indexar_vault(raiz: Path, caminho: str = ".") -> ResultadoFerramenta:
    base = raiz.resolve()
    alvo = resolver_dentro(raiz, caminho, diretorio=True) if caminho not in ("", ".") else base
    notas: dict[str, dict] = {}  # chave: nome da nota em minusculas (como o Obsidian resolve [[links]])
    bytes_total = 0
    truncado = False
    for atual, dirs, nomes in os.walk(alvo, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORAR and not proibido(Path(atual) / d))
        for nome in sorted(nomes):
            p = Path(atual) / nome
            rel = p.resolve().relative_to(base).as_posix()
            if p.suffix.lower() != ".md" or p.is_symlink() or caminho_sensivel(rel):
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue
                texto = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(notas) >= MAX_NOTAS:
                truncado = True
                break
            bytes_total += len(texto.encode("utf-8"))
            notas.setdefault(p.stem.casefold(), {
                "nome": p.stem, "caminho": rel, "links": extrair_wikilinks(texto),
                "tags": sorted(set(extrair_tags(texto)) | set(_frontmatter_tags(texto)))})
        if truncado:
            break
    entradas: Counter[str] = Counter()
    quebrados: dict[str, list[str]] = {}
    for chave, n in notas.items():
        for alvo_nome in n["links"]:
            k = alvo_nome.casefold()
            if k in notas and k != chave:
                entradas[k] += 1
            elif k not in notas:
                quebrados.setdefault(alvo_nome, []).append(n["nome"])
    tags: Counter[str] = Counter(t for n in notas.values() for t in n["tags"])
    orfas = [n["nome"] for k, n in notas.items() if not entradas[k] and not any(
        x.casefold() in notas and x.casefold() != k for x in n["links"])]
    mais_citadas = [(notas[k]["nome"], c) for k, c in entradas.most_common(TOPO)]
    linhas = [f"{len(notas)} nota(s); {sum(len(n['links']) for n in notas.values())} link(s); "
              f"{len(quebrados)} link(s) quebrado(s); {len(orfas)} nota(s) orfa(s)"]
    if mais_citadas:
        linhas.append("mais citadas: " + ", ".join(f"{n} ({c})" for n, c in mais_citadas))
    if tags:
        linhas.append("tags: " + ", ".join(f"#{t} ({c})" for t, c in tags.most_common(TOPO)))
    if quebrados:
        linhas.append("quebrados: " + "; ".join(f"[[{k}]] em {', '.join(v[:3])}" for k, v in list(quebrados.items())[:TOPO]))
    if orfas:
        linhas.append("orfas: " + ", ".join(orfas[:TOPO]) + (" ..." if len(orfas) > TOPO else ""))
    if truncado:
        linhas.append(f"(indexacao interrompida em {MAX_NOTAS} notas)")
    dados = {
        "notas": [{"nome": n["nome"], "caminho": n["caminho"], "links": len(n["links"]), "backlinks": entradas[k],
                   "tags": n["tags"]} for k, n in list(notas.items())[:500]],
        "quebrados": {k: v[:5] for k, v in list(quebrados.items())[:100]},
        "orfas": orfas[:100], "tags": dict(tags.most_common(30)),
    }
    return montar("vault.indexar", "", "\n".join(linhas), dados, truncado, tokens_origem=tokens_de_bytes(bytes_total))
