"""contas de acesso ao painel (usuario e senha) e sessoes

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-14 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usuario",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("nome", sa.String(length=64), nullable=False),
        sa.Column("senha_hash", sa.String(length=300), nullable=False),
        sa.Column("falhas", sa.Integer(), nullable=False),
        sa.Column("bloqueado_ate", sa.String(length=40), nullable=True),
        sa.Column("ultimo_acesso", sa.String(length=40), nullable=True),
        sa.Column("criado_em", sa.String(length=40), nullable=False),
        sa.Column("atualizado_em", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nome"),
    )
    op.create_table(
        "sessao",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("usuario_id", sa.String(length=64), nullable=False),
        sa.Column("criado_em", sa.String(length=40), nullable=False),
        sa.Column("ultimo_uso", sa.String(length=40), nullable=False),
        sa.Column("expira_em", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("sessao", schema=None) as b:
        b.create_index(b.f("ix_sessao_usuario_id"), ["usuario_id"], unique=False)
        b.create_index(b.f("ix_sessao_expira_em"), ["expira_em"], unique=False)


def downgrade() -> None:
    op.drop_table("sessao")
    op.drop_table("usuario")
