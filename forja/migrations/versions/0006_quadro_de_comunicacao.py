"""quadro de comunicacao (blackboard)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-09 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mensagem_quadro",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("versao", sa.Integer(), nullable=False),
        sa.Column("origem", sa.String(length=60), nullable=False),
        sa.Column("destino", sa.String(length=60), nullable=False),
        sa.Column("tipo", sa.String(length=16), nullable=False),
        sa.Column("prioridade", sa.Integer(), nullable=False),
        sa.Column("assunto", sa.String(length=200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("referencias", sa.JSON(), nullable=False),
        sa.Column("tarefa_id", sa.String(length=64), nullable=True),
        sa.Column("estado", sa.String(length=16), nullable=False),
        sa.Column("dedup_key", sa.String(length=100), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("criado_em", sa.String(length=40), nullable=False),
        sa.Column("expira_em", sa.String(length=40), nullable=True),
        sa.Column("entregue_em", sa.String(length=40), nullable=True),
        sa.Column("resolvida_em", sa.String(length=40), nullable=True),
        sa.Column("resolvida_por", sa.String(length=100), nullable=True),
        sa.Column("nota_resolucao", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["tarefa_id"], ["tarefa.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("origem", "dedup_key", name="uq_quadro_origem_dedup"),
    )
    with op.batch_alter_table("mensagem_quadro", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_mensagem_quadro_tarefa_id"), ["tarefa_id"], unique=False)
        batch_op.create_index("ix_quadro_destino_estado_prio", ["destino", "estado", "prioridade"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("mensagem_quadro", schema=None) as batch_op:
        batch_op.drop_index("ix_quadro_destino_estado_prio")
        batch_op.drop_index(batch_op.f("ix_mensagem_quadro_tarefa_id"))
    op.drop_table("mensagem_quadro")
