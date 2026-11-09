"""repo.mapa: visao geral de um repositorio (linguagens, pastas, pontos de entrada, configuracao, testes)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from forja.ferramentas.caminhos import resolver_dentro
from forja.ferramentas.contrato import ResultadoFerramenta, montar, tokens_de_bytes
from forja.memoria.indexador import LINGUAGENS, listar_arquivos

MAX_ARQUIVOS = 20000
ENTRADAS = frozenset({"__main__.py", "main.py", "app.py", "manage.py", "cli.py", "wsgi.py", "asgi.py", "index.js",
                      "index.ts", "server.js", "server.ts"})
CONFIG = ("pyproject.toml", "setup.py", "requirements.txt", "requirements-dev.txt", "package.json", "Dockerfile",
          "docker-compose.yml", "Makefile", "alembic.ini", ".env.example", "README.md", "AGENTS.md", ".gitignore")


def mapa_repositorio(raiz: Path, caminho: str = ".") -> ResultadoFerramenta:
    base = raiz.resolve()
    alvo = resolver_dentro(raiz, caminho, diretorio=True) if caminho not in ("", ".") else base
    linguagens: Counter[str] = Counter()
    pastas: Counter[str] = Counter()
    entradas: list[str] = []
    testes = 0
    total = 0
    bytes_total = 0
    truncado = False
    for p in listar_arquivos(alvo):
        total += 1
        if total > MAX_ARQUIVOS:
            truncado = True
            break
        rel = p.resolve().relative_to(base).as_posix()
        linguagens[LINGUAGENS.get(p.suffix.lower(), "outro")] += 1
        partes = rel.split("/")
        pastas[partes[0] if len(partes) > 1 else "."] += 1
        if p.name in ENTRADAS and len(entradas) < 15:
            entradas.append(rel)
        if "tests" in partes[:-1] or partes[-1].startswith("test_"):
            testes += 1
        try:
            bytes_total += p.stat().st_size
        except OSError:
            pass
    presentes = [c for c in CONFIG if (alvo / c).is_file()]
    linhas = [f"{total} arquivo(s) de codigo/docs ({', '.join(f'{k} {v}' for k, v in linguagens.most_common(6))})"]
    linhas.append("pastas: " + ", ".join(f"{k}/ ({v})" for k, v in pastas.most_common(12)))
    if entradas:
        linhas.append("entradas: " + ", ".join(entradas))
    if presentes:
        linhas.append("config: " + ", ".join(presentes))
    linhas.append(f"arquivos de teste: {testes}")
    if truncado:
        linhas.append("(mapa interrompido no limite)")
    dados = {"arquivos": total, "linguagens": dict(linguagens), "pastas": dict(pastas.most_common(30)),
             "entradas": entradas, "config": presentes, "arquivos_de_teste": testes}
    return montar("repo.mapa", "", "\n".join(linhas), dados, truncado, tokens_origem=tokens_de_bytes(bytes_total))
