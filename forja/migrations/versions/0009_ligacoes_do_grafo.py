"""ligacoes tipadas criadas pela tela do grafo (memoria ou no -> memoria ou no)

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-10 18:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ligacao_grafo",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("origem", sa.String(length=64), nullable=False),
        sa.Column("destino", sa.String(length=64), nullable=False),
        sa.Column("tipo", sa.String(length=32), nullable=False),
        sa.Column("namespace", sa.String(length=200), nullable=False),
        sa.Column("nota", sa.String(length=300), nullable=False),
        sa.Column("criado_por", sa.String(length=100), nullable=False),
        sa.Column("criado_em", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("origem", "destino", "tipo", name="uq_ligacao_grafo"),
    )
    with op.batch_alter_table("ligacao_grafo", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_ligacao_grafo_namespace"), ["namespace"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("ligacao_grafo", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ligacao_grafo_namespace"))
    op.drop_table("ligacao_grafo")
