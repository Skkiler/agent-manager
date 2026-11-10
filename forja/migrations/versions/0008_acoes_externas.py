"""acoes externas (escrita em servicos) com aprovacao por acao

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-10 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acao_externa",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("versao", sa.Integer(), nullable=False),
        sa.Column("integracao", sa.String(length=60), nullable=False),
        sa.Column("acao", sa.String(length=60), nullable=False),
        sa.Column("parametros", sa.JSON(), nullable=False),
        sa.Column("descricao", sa.String(length=400), nullable=False),
        sa.Column("risco", sa.String(length=16), nullable=False),
        sa.Column("estado", sa.String(length=16), nullable=False),
        sa.Column("solicitado_por", sa.String(length=100), nullable=False),
        sa.Column("tarefa_id", sa.String(length=64), nullable=True),
        sa.Column("dedup_key", sa.String(length=100), nullable=True),
        sa.Column("decidido_por", sa.String(length=100), nullable=True),
        sa.Column("adendo", sa.Text(), nullable=False),
        sa.Column("resultado", sa.Text(), nullable=False),
        sa.Column("criado_em", sa.String(length=40), nullable=False),
        sa.Column("decidido_em", sa.String(length=40), nullable=True),
        sa.Column("executado_em", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("solicitado_por", "dedup_key", name="uq_acao_externa_dedup"),
    )
    with op.batch_alter_table("acao_externa", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_acao_externa_estado"), ["estado"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("acao_externa", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_acao_externa_estado"))
    op.drop_table("acao_externa")
