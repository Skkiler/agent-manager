"""reciclagem de sessoes antigas (tarefas terminadas e sub-masters encerrados destilados no segundo cerebro)

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-19 09:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reciclagem",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tipo", sa.String(length=16), nullable=False),
        sa.Column("alvo_id", sa.String(length=64), nullable=False),
        sa.Column("projeto_id", sa.String(length=64), nullable=True),
        sa.Column("memoria_id", sa.String(length=64), nullable=True),
        sa.Column("resultado", sa.String(length=16), nullable=False),
        sa.Column("pontos", sa.Integer(), nullable=False),
        sa.Column("compactado", sa.String(length=16), nullable=False),
        sa.Column("criado_em", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alvo_id"),
    )
    with op.batch_alter_table("reciclagem", schema=None) as b:
        b.create_index(b.f("ix_reciclagem_tipo"), ["tipo"], unique=False)
        b.create_index(b.f("ix_reciclagem_projeto_id"), ["projeto_id"], unique=False)


def downgrade() -> None:
    op.drop_table("reciclagem")
