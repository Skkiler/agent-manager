"""Ambiente Alembic. O engine e injetado por forja.adapters.sqlite.banco (sem alembic.ini)."""

from __future__ import annotations

from alembic import context

from forja.adapters.sqlite.banco import incluir_objeto  # filtra as tabelas FTS5 (ver banco.py)
from forja.adapters.sqlite.tabelas import Base

config = context.config
target_metadata = Base.metadata


def run_migrations() -> None:
    engine = config.attributes["engine"]
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True,
                          include_object=incluir_objeto)
        with context.begin_transaction():
            context.run_migrations()


run_migrations()
