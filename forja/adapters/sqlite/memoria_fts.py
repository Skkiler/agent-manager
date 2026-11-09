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
        text("INSERT INTO memoria_fts(titulo, resumo, conteudo, tags, memoria_id, namespace) "
             "VALUES (:titulo, :resumo, :conteudo, :tags, :id, :ns)"),
        {"titulo": mem["titulo"], "resumo": mem["resumo"], "conteudo": mem["conteudo"],
         "tags": " ".join(mem["tags"] or []), "id": mem["id"], "ns": mem["namespace"]},
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
def codigo_substituir_arquivo(t: Tx, arquivo_id: str, namespace: str, caminho: str, nomes: str,
                              trechos: list[tuple[int, int, str]]) -> None:
    codigo_remover_arquivo(t, arquivo_id)
    for ini, fim, texto in trechos:
        t.s.execute(
            text("INSERT INTO codigo_fts(caminho, nomes, texto, arquivo_id, namespace, linha_ini, linha_fim) "
                 "VALUES (:c, :n, :t, :a, :ns, :i, :f)"),
            {"c": caminho, "n": nomes, "t": texto, "a": arquivo_id, "ns": namespace, "i": ini, "f": fim},
        )


def codigo_remover_arquivo(t: Tx, arquivo_id: str) -> None:
    t.s.execute(text("DELETE FROM codigo_fts WHERE arquivo_id = :a"), {"a": arquivo_id})


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


def simbolos_buscar(t: Tx, tokens: list[str], namespaces: list[str], limite: int) -> list[dict[str, Any]]:
    """Ranker de SIMBOLOS (secao 10.2): nome exato > componente final de 'Classe.metodo' > prefixo. ACL na consulta."""
    if not tokens:
        return []
    filtro, params = _filtro_ns(namespaces, "a.namespace")
    pontos, condicoes = [], []
    for i, tok in enumerate(tokens):
        params[f"t{i}"] = tok.casefold()
        exato = f"lower(s.nome) = :t{i}"
        final = f"substr(lower(s.nome), -(length(:t{i}) + 1)) = '.' || :t{i}"
        prefixo = f"substr(lower(s.nome), 1, length(:t{i})) = :t{i}"
        condicoes.append(f"({exato} OR {final} OR {prefixo})")
        pontos.append(f"(CASE WHEN {exato} THEN 3 WHEN {final} THEN 2 WHEN {prefixo} THEN 1 ELSE 0 END)")
    sql = (
        "SELECT s.nome AS nome, s.tipo AS tipo, s.linha AS linha, a.id AS arquivo_id, "  # noqa: S608 - so marcadores :tN/:nN e identificadores fixos; valores vao em parametros
        "a.caminho AS caminho, a.namespace AS namespace, "
        f"({' + '.join(pontos)}) AS pontos "
        "FROM simbolo s JOIN arquivo_indexado a ON a.id = s.arquivo_id "
        f"WHERE a.estado = 'ativo' AND s.tipo != 'import' AND ({' OR '.join(condicoes)}) AND {filtro} "
        "ORDER BY pontos DESC, length(s.nome), s.linha LIMIT :lim"
    )
    linhas = t.s.execute(text(sql), {"lim": limite, **params}).mappings().all()
    return [dict(r) for r in linhas]


def trecho_que_contem(t: Tx, arquivo_id: str, linha: int) -> dict[str, Any] | None:
    """Trecho indexado (ja redigido) que cobre `linha`: fonte do snippet de uma definicao."""
    r = t.s.execute(
        text("SELECT texto, linha_ini, linha_fim FROM codigo_fts WHERE arquivo_id = :a "
             "AND linha_ini <= :l AND linha_fim >= :l ORDER BY linha_ini DESC LIMIT 1"),
        {"a": arquivo_id, "l": linha}).mappings().first()
    return dict(r) if r else None
