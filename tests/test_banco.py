"""Testes de migracao, integridade, backup e restauracao do SQLite."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.banco import (
    backup,
    criar_engines,
    migrar,
    rebaixar,
    restaurar,
    verificar_integridade,
)
from forja.adapters.sqlite.repositorio import RepositorioSqlite


def test_migracao_cria_tabelas(tmp_path: Path):
    db = tmp_path / "f.sqlite3"
    migrar(db)
    w, r = criar_engines(db)
    tabelas = set(inspect(w).get_table_names())
    RepositorioSqlite(w, r).fechar()
    assert {"projeto", "objetivo", "tarefa", "execucao", "evento", "artefato", "idempotencia"} <= tabelas


def test_downgrade_remove_tabelas(tmp_path: Path):
    db = tmp_path / "f.sqlite3"
    migrar(db)
    rebaixar(db, "base")
    w, r = criar_engines(db)
    assert "tarefa" not in set(inspect(w).get_table_names())
    RepositorioSqlite(w, r).fechar()


def test_backup_restore_preserva_dados(tmp_path: Path):
    db = tmp_path / "f.sqlite3"
    migrar(db)
    w, r = criar_engines(db)
    repo = RepositorioSqlite(w, r)
    with repo.escrita() as tx:
        tx.inserir(T.Projeto, id="P-1", nome="demo", descricao="", estado="ativo", criado_em="2026-01-01T00:00:00Z")
    destino = tmp_path / "bkp" / "f.bak.sqlite3"
    backup(db, destino)
    verificar_integridade(destino)
    restaurado = tmp_path / "restaurado.sqlite3"
    restaurar(destino, restaurado)
    w2, r2 = criar_engines(restaurado)
    repo2 = RepositorioSqlite(w2, r2)
    with repo2.leitura() as tx:
        assert tx.obter(T.Projeto, "P-1")["nome"] == "demo"
    repo.fechar()
    repo2.fechar()


def test_migracao_0003_cria_fts5_e_downgrade_remove(tmp_path: Path):
    import sqlite3

    db = tmp_path / "fts.sqlite3"
    migrar(db)
    con = sqlite3.connect(str(db))
    try:
        tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"memoria", "memoria_versao", "memoria_evidencia", "no_conhecimento", "aresta_conhecimento",
                "arquivo_indexado", "simbolo", "memoria_fts", "codigo_fts"} <= tabelas
        con.execute("INSERT INTO memoria_fts(titulo, resumo, conteudo, tags, memoria_id, namespace) "
                    "VALUES ('Titulo', 'r', 'conteudo', 't', 'M1', 'publico')")
        assert con.execute("SELECT memoria_id FROM memoria_fts WHERE memoria_fts MATCH 'titulo'").fetchone() == ("M1",)
    finally:
        con.close()
    rebaixar(db, "0002")
    con = sqlite3.connect(str(db))
    try:
        restantes = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "memoria" not in restantes and not any(n.startswith(("memoria_fts", "codigo_fts")) for n in restantes)
        assert "aprovacao" in restantes  # 0002 intacta
    finally:
        con.close()
