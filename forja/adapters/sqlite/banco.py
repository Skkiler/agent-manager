"""Engines SQLite (WAL), migracoes Alembic, backup e restauracao consistentes."""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


# Tabelas virtuais FTS5 e suas tabelas-sombra NAO sao modeladas pelo SQLAlchemy. Sem este filtro, o autogenerate as trata
# como "orfas" e propoe APAGA-LAS (o que destruiria o indice de memoria/codigo). Usado pelo env.py e pelos testes.
PREFIXOS_FTS = ("memoria_fts", "codigo_fts")


def incluir_objeto(objeto, nome, tipo, reflected, compare_to) -> bool:  # noqa: ANN001
    return not (tipo == "table" and nome and nome.startswith(PREFIXOS_FTS))


def _url(caminho: Path) -> str:
    return f"sqlite:///{caminho.resolve().as_posix()}"


def _configurar(engine: Engine, begin_sql: str) -> Engine:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _rec):  # pragma: no cover - exercitado indiretamente
        dbapi_conn.isolation_level = None  # transacoes controladas pelo evento 'begin'
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=10000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
        conn.exec_driver_sql(begin_sql)

    return engine


def criar_engines(caminho: Path) -> tuple[Engine, Engine]:
    """(escrita, leitura). Escrita usa BEGIN IMMEDIATE: escritores serializados, sem upgrade de lock."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    args = {"check_same_thread": False}
    w = _configurar(create_engine(_url(caminho), connect_args=args), "BEGIN IMMEDIATE")
    r = _configurar(create_engine(_url(caminho), connect_args=args), "BEGIN")
    return w, r


def configuracao_alembic(caminho: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["engine"] = create_engine(_url(caminho))
    return cfg


def migrar(caminho: Path, destino: str = "head") -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    cfg = configuracao_alembic(caminho)
    try:
        command.upgrade(cfg, destino)
    finally:
        cfg.attributes["engine"].dispose()


def rebaixar(caminho: Path, destino: str = "base") -> None:
    cfg = configuracao_alembic(caminho)
    try:
        command.downgrade(cfg, destino)
    finally:
        cfg.attributes["engine"].dispose()


def backup(origem: Path, destino: Path) -> Path:
    """Copia consistente via API de backup do SQLite (seguro com o servidor em execucao)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        raise FileExistsError(f"destino ja existe: {destino}")
    src = sqlite3.connect(f"file:{origem.resolve().as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(destino))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    verificar_integridade(destino)
    return destino


def verificar_integridade(caminho: Path) -> None:
    con = sqlite3.connect(str(caminho))
    try:
        res = con.execute("PRAGMA integrity_check").fetchone()
    finally:
        con.close()
    if not res or res[0] != "ok":
        raise RuntimeError(f"integrity_check falhou para {caminho.name}: {res}")


def restaurar(backup_path: Path, destino: Path) -> None:
    """Restaura um backup verificado. O servidor deve estar parado (WAL/SHM antigos sao removidos)."""
    verificar_integridade(backup_path)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(destino.suffix + ".restore")
    shutil.copyfile(backup_path, tmp)
    for sufixo in ("-wal", "-shm"):
        p = Path(str(destino) + sufixo)
        if p.exists():
            p.unlink()
    os.replace(tmp, destino)
