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
