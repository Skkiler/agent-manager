"""Integridade das migracoes: cadeia linear, sem deriva em relacao aos modelos e ciclo completo de downgrade/upgrade."""

from __future__ import annotations

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from forja.adapters.sqlite import tabelas as T
from forja.adapters.sqlite.banco import configuracao_alembic, incluir_objeto, migrar, rebaixar


def _revisoes(tmp_path: Path) -> list[str]:
    cfg = configuracao_alembic(tmp_path / "x.sqlite3")
    try:
        return [r.revision for r in reversed(list(ScriptDirectory.from_config(cfg).walk_revisions()))]
    finally:
        cfg.attributes["engine"].dispose()


def _tabelas(caminho: Path) -> set[str]:
    eng = create_engine(f"sqlite:///{caminho.as_posix()}")
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


def test_cadeia_de_revisoes_e_linear_e_sem_buracos(tmp_path: Path):
    revs = _revisoes(tmp_path)
    assert revs == [f"{i:04d}" for i in range(1, len(revs) + 1)], revs
    assert len(revs) >= 7


def test_head_nao_diverge_dos_modelos(tmp_path: Path):
    db = tmp_path / "f.sqlite3"
    migrar(db)
    eng = create_engine(f"sqlite:///{db.as_posix()}")
    try:
        with eng.connect() as c:
            diff = compare_metadata(MigrationContext.configure(c, opts={"include_object": incluir_objeto}), T.Base.metadata)
    finally:
        eng.dispose()
    assert diff == [], f"modelos e migracoes divergem: {diff}"


def test_cada_downgrade_e_cada_upgrade_funcionam_passo_a_passo(tmp_path: Path):
    db = tmp_path / "f.sqlite3"
    revs = _revisoes(tmp_path)
    migrar(db)
    completo = _tabelas(db)
    for anterior in reversed(["base", *revs[:-1]]):  # head -> ... -> base, uma revisao por vez
        rebaixar(db, anterior)
    assert not (_tabelas(db) - {"alembic_version"})  # nada sobra apos voltar a base
    for r in revs:  # base -> head, uma por vez
        migrar(db, r)
    assert _tabelas(db) == completo


def test_downgrade_de_uma_revisao_preserva_os_dados_das_anteriores(tmp_path: Path):
    db = tmp_path / "f.sqlite3"
    migrar(db, "0005")
    eng = create_engine(f"sqlite:///{db.as_posix()}")
    try:
        with eng.begin() as c:
            c.execute(text("INSERT INTO projeto (id, nome, descricao, estado, criado_em) VALUES ('P1','p','', 'ativo','2026')"))
    finally:
        eng.dispose()
    migrar(db)  # 0006, 0007
    rebaixar(db, "0005")
    eng = create_engine(f"sqlite:///{db.as_posix()}")
    try:
        with eng.connect() as c:
            assert c.execute(text("SELECT nome FROM projeto WHERE id='P1'")).scalar() == "p"
    finally:
        eng.dispose()
    assert "mensagem_quadro" not in _tabelas(db) and "configuracao" not in _tabelas(db)


def test_fts5_sobrevive_a_um_ciclo_de_migracao(tmp_path: Path):
    db = tmp_path / "f.sqlite3"
    migrar(db)
    assert {"memoria_fts", "codigo_fts"} <= _tabelas(db)
    rebaixar(db, "0006")
    migrar(db)
    assert {"memoria_fts", "codigo_fts"} <= _tabelas(db)  # o autogenerate nunca pode ter proposto apaga-las
