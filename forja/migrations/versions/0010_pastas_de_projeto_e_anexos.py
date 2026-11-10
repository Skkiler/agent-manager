"""pastas de projeto (trabalho/consulta) e anexos de tarefa

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-11 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projeto", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pastas", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("versao", sa.Integer(), nullable=False, server_default="1"))
    op.create_table(
        "anexo",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tarefa_id", sa.String(length=64), nullable=False),
        sa.Column("nome", sa.String(length=200), nullable=False),
        sa.Column("origem", sa.String(length=16), nullable=False),
        sa.Column("caminho", sa.String(length=500), nullable=True),
        sa.Column("mime", sa.String(length=100), nullable=False),
        sa.Column("tamanho", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("truncado", sa.Boolean(), nullable=False),
        sa.Column("criado_em", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["tarefa_id"], ["tarefa.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("anexo", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_anexo_tarefa_id"), ["tarefa_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("anexo", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_anexo_tarefa_id"))
    op.drop_table("anexo")
    with op.batch_alter_table("projeto", schema=None) as batch_op:
        batch_op.drop_column("versao")
        batch_op.drop_column("pastas")
