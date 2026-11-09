"""SQL do FTS5 (memoria_fts, codigo_fts). Isolado do servico: aqui so existe SQL parametrizado.

ACL: o filtro de namespace e aplicado NA consulta (junto do MATCH), nunca depois no Python. Comparacao por prefixo usa
`substr` (e nao LIKE, onde '_' e '%' funcionam como curinga e vazariam entre namespaces).
Limite conhecido: o IDF do bm25 considera o corpus inteiro do indice, inclusive linhas fora da ACL. Nenhum conteudo
vaza, apenas uma influencia numerica minima no ranking. Mitigacao futura: um indice FTS por sensibilidade.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from forja.adapters.sqlite.repositorio import Tx


def _filtro_ns(namespaces: list[str], coluna: str = "namespace") -> tuple[str, dict[str, str]]:
    """Fragmento SQL so com marcadores :nN (valores vao em parametros): nenhum dado externo e interpolado."""
    partes, params = [], {}
    for i, ns in enumerate(namespaces):
        partes.append(f"({coluna} = :n{i} OR substr({coluna}, 1, length(:n{i}) + 1) = :n{i} || '/')")
        params[f"n{i}"] = ns
    return "(" + " OR ".join(partes) + ")", params


# ------------------------------------------------------------------ memoria
def memoria_indexar(t: Tx, mem: dict[str, Any]) -> None:
    memoria_remover(t, mem["id"])
    t.s.execute(
        text(
            "INSERT INTO memoria_fts(titulo, resumo, conteudo, tags, memoria_id, namespace) "
            "VALUES (:titulo, :resumo, :conteudo, :tags, :id, :ns)"
        ),
        {
            "titulo": mem["titulo"],
            "resumo": mem["resumo"],
            "conteudo": mem["conteudo"],
            "tags": " ".join(mem["tags"] or []),
            "id": mem["id"],
            "ns": mem["namespace"],
        },
    )


def memoria_remover(t: Tx, memoria_id: str) -> None:
    t.s.execute(text("DELETE FROM memoria_fts WHERE memoria_id = :id"), {"id": memoria_id})


def memoria_buscar(t: Tx, match: str, namespaces: list[str], limite: int) -> list[dict[str, Any]]:
    filtro, params = _filtro_ns(namespaces)
    sql = (
        "SELECT memoria_id, bm25(memoria_fts, 8.0, 3.0, 1.0, 2.0, 0.0, 0.0) AS pontuacao, "  # noqa: S608 - so marcadores :nN e identificadores fixos; valores vao em parametros
        "snippet(memoria_fts, -1, '«', '»', '…', 24) AS trecho "
        f"FROM memoria_fts WHERE memoria_fts MATCH :m AND {filtro} ORDER BY pontuacao LIMIT :lim"
    )
    linhas = t.s.execute(text(sql), {"m": match, "lim": limite, **params}).mappings().all()
    return [dict(r) for r in linhas]


# ------------------------------------------------------------------ codigo
def codigo_substituir_arquivo(
    t: Tx, arquivo_id: str, namespace: str, caminho: str, nomes: str, trechos: list[tuple[int, int, str]]
) -> None:
    """Troca todos os trechos do arquivo. O id em `codigo_trecho` e usado como rowid do FTS5 (remocao/consulta O(log n))."""
    codigo_remover_arquivo(t, arquivo_id)
    if not trechos:
        return
    ids = []
    for ini, fim, _texto in trechos:
        ids.append(
            t.s.execute(
                text("INSERT INTO codigo_trecho(arquivo_id, linha_ini, linha_fim) VALUES (:a, :i, :f)"),
                {"a": arquivo_id, "i": ini, "f": fim},
            ).lastrowid
        )
    t.s.execute(
        text(
            "INSERT INTO codigo_fts(rowid, caminho, nomes, texto, arquivo_id, namespace, linha_ini, linha_fim) "
            "VALUES (:r, :c, :n, :t, :a, :ns, :i, :f)"
        ),
        [
            {"r": rid, "c": caminho, "n": nomes, "t": texto, "a": arquivo_id, "ns": namespace, "i": ini, "f": fim}
            for rid, (ini, fim, texto) in zip(ids, trechos, strict=True)
        ],
    )


def codigo_remover_arquivo(t: Tx, arquivo_id: str) -> None:
    ids = [r[0] for r in t.s.execute(text("SELECT id FROM codigo_trecho WHERE arquivo_id = :a"), {"a": arquivo_id})]
    if ids:
        t.s.execute(text("DELETE FROM codigo_fts WHERE rowid = :r"), [{"r": i} for i in ids])
        t.s.execute(text("DELETE FROM codigo_trecho WHERE arquivo_id = :a"), {"a": arquivo_id})


def codigo_buscar(t: Tx, match: str, namespaces: list[str], limite: int) -> list[dict[str, Any]]:
    filtro, params = _filtro_ns(namespaces)
    sql = (
        "SELECT arquivo_id, caminho, namespace, linha_ini, linha_fim, "  # noqa: S608 - so marcadores :nN e identificadores fixos; valores vao em parametros
        "bm25(codigo_fts, 6.0, 8.0, 1.0, 0.0, 0.0, 0.0, 0.0) AS pontuacao, "
        "snippet(codigo_fts, -1, '«', '»', '…', 24) AS trecho "
        f"FROM codigo_fts WHERE codigo_fts MATCH :m AND {filtro} ORDER BY pontuacao LIMIT :lim"
    )
    linhas = t.s.execute(text(sql), {"m": match, "lim": limite, **params}).mappings().all()
    return [dict(r) for r in linhas]


def simbolos_buscar(
    t: Tx, termos: list[str] | list[list[str]], namespaces: list[str], limite: int
) -> list[dict[str, Any]]:
    """Ranker de SIMBOLOS (secao 10.2): nome exato > componente final de 'Classe.metodo' > prefixo. ACL na consulta.

    `termos` e uma lista de grupos de alternativas (ex.: [["autenticar", "autentic"]]): cada GRUPO conta uma vez.
    Cada hit traz `casados` = quantos grupos o nome do simbolo cobre (base da cobertura da consulta)."""
    grupos = [[g] if isinstance(g, str) else list(g) for g in termos]
    grupos = [g for g in grupos if g]
    if not grupos:
        return []
    filtro, params = _filtro_ns(namespaces, "a.namespace")
    pontos, casados, condicoes = [], [], []
    for gi, alternativas in enumerate(grupos):
        conds, notas = [], []
        for ai, tok in enumerate(alternativas):
            k = f"{gi}_{ai}"
            params[f"t{k}"] = tok.casefold()
            params[f"u{k}"] = tok.casefold() + "\U0010ffff"  # limite superior do intervalo de prefixo (usa o indice)
            exato = f"s.nome_norm = :t{k}"
            final = f"s.nome_final = :t{k}"
            prefixo = f"(s.nome_norm >= :t{k} AND s.nome_norm < :u{k})"
            conds.append(f"({exato} OR {final} OR {prefixo})")
            notas.append(f"(CASE WHEN {exato} THEN 3 WHEN {final} THEN 2 WHEN {prefixo} THEN 1 ELSE 0 END)")
        cond = "(" + " OR ".join(conds) + ")"
        condicoes.append(cond)
        casados.append(f"(CASE WHEN {cond} THEN 1 ELSE 0 END)")
        pontos.append(notas[0] if len(notas) == 1 else "max(" + ", ".join(notas) + ")")
    sql = (  # noqa: S608 - so marcadores :tN/:uN/:nN e identificadores fixos; valores vao em parametros
        "SELECT s.nome AS nome, s.tipo AS tipo, s.linha AS linha, a.id AS arquivo_id, "  # noqa: S608 - placeholders fixos; valores em parametros
        "a.caminho AS caminho, a.namespace AS namespace, "
        f"({' + '.join(pontos)}) AS pontos, ({' + '.join(casados)}) AS casados "
        "FROM simbolo s JOIN arquivo_indexado a ON a.id = s.arquivo_id "
        f"WHERE a.estado = 'ativo' AND s.tipo != 'import' AND ({' OR '.join(condicoes)}) AND {filtro} "
        "ORDER BY casados DESC, pontos DESC, length(s.nome), s.linha LIMIT :lim"
    )
    linhas = t.s.execute(text(sql), {"lim": limite, **params}).mappings().all()
    return [dict(r) | {"grupos": len(grupos)} for r in linhas]


def trecho_que_contem(t: Tx, arquivo_id: str, linha: int) -> dict[str, Any] | None:
    """Trecho indexado (ja redigido) que cobre `linha`: fonte do snippet de uma definicao."""
    ref = t.s.execute(
        text(
            "SELECT id FROM codigo_trecho WHERE arquivo_id = :a AND linha_ini <= :l AND linha_fim >= :l "
            "ORDER BY linha_ini DESC LIMIT 1"
        ),
        {"a": arquivo_id, "l": linha},
    ).first()
    if ref is None:
        return None
    r = (
        t.s.execute(text("SELECT texto, linha_ini, linha_fim FROM codigo_fts WHERE rowid = :r"), {"r": ref[0]})
        .mappings()
        .first()
    )
    return dict(r) if r else None


# ------------------------------------------------------------------ grafo (ranker por relacao)
def grafo_nos_por_nome(t: Tx, termos: list[str], namespaces: list[str], limite: int = 20) -> list[dict[str, Any]]:
    """Nos do grafo de conhecimento cujo nome casa (exato ou prefixo) com algum termo. ACL na consulta."""
    if not termos:
        return []
    filtro, params = _filtro_ns(namespaces)
    cond = []
    for i, tok in enumerate(termos):
        params[f"g{i}"] = tok.casefold()
        cond.append(f"(lower(nome) = :g{i} OR substr(lower(nome), 1, length(:g{i})) = :g{i})")
    sql = (  # noqa: S608 - so marcadores :gN/:nN e identificadores fixos; valores vao em parametros
        f"SELECT id, nome, tipo, namespace FROM no_conhecimento WHERE ({' OR '.join(cond)}) AND {filtro} LIMIT :lim"  # noqa: S608 - placeholders fixos; valores em parametros
    )
    return [dict(r) for r in t.s.execute(text(sql), {"lim": limite, **params}).mappings().all()]


def grafo_vizinhos(t: Tx, ids: list[str], namespaces: list[str]) -> list[dict[str, Any]]:
    """Arestas (1 salto) que tocam `ids`, com o no do outro lado. Aresta e no precisam estar na ACL pedida."""
    if not ids:
        return []
    f_ar, p_ar = _filtro_ns(namespaces, "a.namespace")
    f_no, p_no = _filtro_ns(namespaces, "n.namespace")
    params = {f"i{k}": v for k, v in enumerate(ids)}
    marcadores = ", ".join(f":i{k}" for k in range(len(ids)))
    p_no = {k.replace("n", "m", 1): v for k, v in p_no.items()}
    f_no = f_no.replace(":n", ":m")
    sql = (  # noqa: S608 - so marcadores :iN/:nN/:mN e identificadores fixos; valores vao em parametros
        "SELECT a.tipo AS relacao, a.origem AS origem, a.destino AS destino, n.id AS vizinho_id, n.nome AS vizinho_nome "
        "FROM aresta_conhecimento a JOIN no_conhecimento n "
        "ON n.id = CASE WHEN a.origem IN (" + marcadores + ") THEN a.destino ELSE a.origem END "
        f"WHERE (a.origem IN ({marcadores}) OR a.destino IN ({marcadores})) AND {f_ar} AND {f_no}"
    )
    return [dict(r) for r in t.s.execute(text(sql), {**params, **p_ar, **p_no}).mappings().all()]


def memorias_com_refs(t: Tx, namespaces: list[str]) -> list[tuple[str, list[str]]]:
    """(id, refs) das memorias nos namespaces pedidos; o cruzamento com ids de nos e feito no servico."""
    filtro, params = _filtro_ns(namespaces)
    sql = f"SELECT id, refs FROM memoria WHERE {filtro}"  # noqa: S608 - fragmento so com marcadores :nN
    saida = []
    import json

    for r in t.s.execute(text(sql), params):
        refs = json.loads(r[1]) if isinstance(r[1], str) else (r[1] or [])
        saida.append((r[0], list(refs)))
    return saida


def contar(t: Tx, tabela: str, match: str, namespaces: list[str]) -> int:
    """Frequencia de documento (quantas linhas casam) dentro da ACL. Base da relaxacao por raridade."""
    if tabela not in ("memoria_fts", "codigo_fts"):
        raise ValueError("tabela invalida")
    filtro, params = _filtro_ns(namespaces)
    sql = f"SELECT count(*) FROM {tabela} WHERE {tabela} MATCH :m AND {filtro}"  # noqa: S608 - tabela validada acima
    return int(t.s.execute(text(sql), {"m": match, **params}).scalar() or 0)


def ids_casados(t: Tx, tabela: str, match: str, namespaces: list[str], limite: int = 2000) -> set[tuple]:
    """Chaves dos documentos que casam `match` (memoria: (id,); codigo: (arquivo_id, linha_ini)). Dentro da ACL."""
    colunas = {"memoria_fts": "memoria_id", "codigo_fts": "arquivo_id, linha_ini"}
    if tabela not in colunas:
        raise ValueError("tabela invalida")
    filtro, params = _filtro_ns(namespaces)
    sql = f"SELECT {colunas[tabela]} FROM {tabela} WHERE {tabela} MATCH :m AND {filtro} LIMIT :lim"  # noqa: S608
    return {tuple(r) for r in t.s.execute(text(sql), {"m": match, "lim": limite, **params})}


def total_documentos(t: Tx, tabela: str, namespaces: list[str]) -> int:
    if tabela not in ("memoria_fts", "codigo_fts"):
        raise ValueError("tabela invalida")
    filtro, params = _filtro_ns(namespaces)
    sql = f"SELECT count(*) FROM {tabela} WHERE {filtro}"  # noqa: S608 - tabela validada; filtro so com marcadores
    return int(t.s.execute(text(sql), params).scalar() or 0)
