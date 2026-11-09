"""sql.inspecionar: tabelas, colunas e indices de um banco SQLite, em modo somente leitura e sem ler linhas."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from forja.dominio.erros import ValidacaoDominio
from forja.ferramentas.caminhos import resolver_dentro
from forja.ferramentas.contrato import ResultadoFerramenta, montar

MAX_TABELAS = 60
_SOMBRAS = ("_data", "_idx", "_content", "_docsize", "_config")


def _aspas(nome: str) -> str:
    return '"' + nome.replace('"', '""') + '"'


def inspecionar_sqlite(raiz: Path, caminho: str) -> ResultadoFerramenta:
    real = resolver_dentro(raiz, caminho)
    with real.open("rb") as f:
        if f.read(16) != b"SQLite format 3\x00":
            raise ValidacaoDominio("nao e um banco SQLite")
    con = sqlite3.connect(f"{real.as_uri()}?mode=ro", uri=True, timeout=2)
    try:
        con.execute("PRAGMA query_only = ON")
        objetos = con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        virtuais = {n for t, n, _, sql in objetos if t == "table" and (sql or "").upper().startswith("CREATE VIRTUAL")}
        sombra = {n for t, n, _, _ in objetos if t == "table" and any(n == v + s for v in virtuais for s in _SOMBRAS)}
        tabelas = [(n, n in virtuais) for t, n, _, _ in objetos if t == "table" and n not in sombra]
        saida: list[dict] = []
        for nome, virtual in tabelas[:MAX_TABELAS]:
            cols = [] if virtual else con.execute(f"PRAGMA table_info({_aspas(nome)})").fetchall()  # noqa: S608
            idx = [i for t, i, tb, _ in objetos if t == "index" and tb == nome and not i.startswith("sqlite_autoindex")]
            fks = 0 if virtual else len(con.execute(f"PRAGMA foreign_key_list({_aspas(nome)})").fetchall())  # noqa: S608
            saida.append({
                "tabela": nome, "virtual": virtual, "indices": idx, "chaves_estrangeiras": fks,
                "colunas": [{"nome": c[1], "tipo": c[2], "obrigatoria": bool(c[3]), "pk": bool(c[5])} for c in cols],
            })
    except sqlite3.DatabaseError as e:
        raise ValidacaoDominio(f"banco ilegivel: {type(e).__name__}") from e
    finally:
        con.close()
    linhas = [f"{real.name}: {len(tabelas)} tabela(s), {len(sombra)} sombra(s) de FTS omitida(s)"]
    for t in saida:
        if t["virtual"]:
            linhas.append(f"- {t['tabela']} (virtual/FTS)")
            continue
        cols = ", ".join(f"{c['nome']} {c['tipo']}{' PK' if c['pk'] else ''}{' !' if c['obrigatoria'] else ''}"
                         for c in t["colunas"])
        extra = f" | idx: {', '.join(t['indices'])}" if t["indices"] else ""
        fk = f" | fk: {t['chaves_estrangeiras']}" if t["chaves_estrangeiras"] else ""
        linhas.append(f"- {t['tabela']}({cols}){extra}{fk}")
    truncado = len(tabelas) > MAX_TABELAS
    if truncado:
        linhas.append(f"(+{len(tabelas) - MAX_TABELAS} tabelas omitidas)")
    dados = {"arquivo": real.name, "tabelas": saida, "tabelas_sombra_omitidas": len(sombra)}
    ddl = "\n".join(sql or "" for _, _, _, sql in objetos)  # linha de base: ler o DDL completo
    return montar("sql.inspecionar", ddl, "\n".join(linhas), dados, truncado, ["nenhuma linha de dados foi lida"])
