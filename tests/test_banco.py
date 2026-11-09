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


def test_autogenerate_no_head_nao_propoe_nada_e_nunca_apaga_fts(tmp_path: Path):
    """Regressao: o autogenerate propunha DROP das tabelas FTS5 (destruiria o indice de memoria). Banco em 'head' = sem ops."""
    from alembic.autogenerate import produce_migrations
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    from forja.adapters.sqlite.banco import incluir_objeto
    from forja.adapters.sqlite.tabelas import Base

    db = tmp_path / "ag.sqlite3"
    migrar(db)
    eng = create_engine(f"sqlite:///{db.as_posix()}")
    try:
        with eng.connect() as c:
            sem_filtro = produce_migrations(MigrationContext.configure(c), Base.metadata).upgrade_ops
            com_filtro = produce_migrations(MigrationContext.configure(c, opts={"include_object": incluir_objeto}),
                                            Base.metadata).upgrade_ops
        apagaria_fts = [op.table_name for op in sem_filtro.ops if getattr(op, "table_name", "").startswith(("memoria_fts", "codigo_fts"))]
        assert apagaria_fts, "o problema que o filtro resolve deixou de existir? (sem filtro deveria propor DROP do FTS)"
        assert com_filtro.is_empty(), com_filtro.ops
    finally:
        eng.dispose()


def test_migracao_0004_cria_conversa_e_contexto_sem_tocar_no_fts(tmp_path: Path):
    import sqlite3

    db = tmp_path / "m4.sqlite3"
    migrar(db, "0003")
    con = sqlite3.connect(str(db))
    con.execute("INSERT INTO memoria_fts(titulo, resumo, conteudo, tags, memoria_id, namespace) "
                "VALUES ('t', 'r', 'conteudo-preservado', '', 'M1', 'publico')")
    con.commit()
    con.close()
    migrar(db)  # 0003 -> 0004 (head)
    con = sqlite3.connect(str(db))
    try:
        tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"mensagem", "contexto_uso", "memoria_fts", "codigo_fts"} <= tabelas
        assert con.execute("SELECT memoria_id FROM memoria_fts WHERE memoria_fts MATCH 'conteudo'").fetchone() == ("M1",)
    finally:
        con.close()
    rebaixar(db, "0003")
    con = sqlite3.connect(str(db))
    try:
        restantes = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "mensagem" not in restantes and "contexto_uso" not in restantes and "memoria_fts" in restantes
    finally:
        con.close()


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


def test_migracao_0005_faz_backfill_de_banco_ja_populado(tmp_path: Path):
    """Banco da Fase 3/4 (sem codigo_trecho nem nome_norm) deve ser migrado sem perder nem reindexar nada."""
    import sqlite3

    db = tmp_path / "m5.sqlite3"
    migrar(db, "0004")
    con = sqlite3.connect(str(db))
    con.execute("INSERT INTO arquivo_indexado VALUES ('ARQ1','publico','r','a.py','h',NULL,'python',10,'ativo',NULL,'2026')")
    con.execute("INSERT INTO simbolo(arquivo_id, nome, tipo, linha, assinatura) VALUES ('ARQ1','Servico.Executar','metodo',3,'')")
    con.execute("INSERT INTO simbolo(arquivo_id, nome, tipo, linha, assinatura) VALUES ('ARQ1','Raiz','classe',1,'')")
    con.execute("INSERT INTO codigo_fts(caminho, nomes, texto, arquivo_id, namespace, linha_ini, linha_fim) "
                "VALUES ('a.py','Raiz','class Raiz: pass','ARQ1','publico',1,20)")
    con.commit()
    con.close()
    migrar(db)  # 0004 -> 0005
    con = sqlite3.connect(str(db))
    try:
        fts_rowid = con.execute("SELECT rowid FROM codigo_fts").fetchone()[0]
        assert con.execute("SELECT id, arquivo_id, linha_ini, linha_fim FROM codigo_trecho").fetchall() == [(fts_rowid, "ARQ1", 1, 20)]
        nomes = {n: (a, b) for n, a, b in con.execute("SELECT nome, nome_norm, nome_final FROM simbolo")}
        assert nomes == {"Servico.Executar": ("servico.executar", "executar"), "Raiz": ("raiz", "raiz")}
        # inserir novo trecho depois do backfill nao pode colidir com o rowid herdado
        con.execute("INSERT INTO codigo_trecho(arquivo_id, linha_ini, linha_fim) VALUES ('ARQ1', 21, 40)")
        assert con.execute("SELECT max(id) FROM codigo_trecho").fetchone()[0] > fts_rowid
    finally:
        con.close()
    rebaixar(db, "0004")
    con = sqlite3.connect(str(db))
    try:
        tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        colunas = {r[1] for r in con.execute("PRAGMA table_info(simbolo)")}
        assert "codigo_trecho" not in tabelas and "nome_norm" not in colunas and "codigo_fts" in tabelas
    finally:
        con.close()
