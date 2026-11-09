"""conversa e uso de contexto

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-08 22:09:37.823256

ATENCAO: o autogenerate propunha apagar as tabelas virtuais FTS5 (memoria_fts, codigo_fts e sombras), pois o SQLAlchemy
nao as modela. Isso destruiria o indice de memoria e de codigo. Esta migracao foi reduzida ao que interessa e o env.py agora
ignora essas tabelas (include_object), evitando a recorrencia.
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contexto_uso",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tarefa_id", sa.String(length=64), nullable=False),
        sa.Column("execucao_id", sa.String(length=64), nullable=False),
        sa.Column("itens", sa.JSON(), nullable=False),
        sa.Column("tokens_contexto", sa.Integer(), nullable=False),
        sa.Column("tokens_prompt", sa.Integer(), nullable=False),
        sa.Column("orcamento", sa.Integer(), nullable=False),
        sa.Column("omitidos", sa.JSON(), nullable=False),
        sa.Column("termos", sa.JSON(), nullable=False),
        sa.Column("uteis", sa.JSON(), nullable=True),
        sa.Column("criado_em", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(
            ["tarefa_id"],
            ["tarefa.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execucao_id"),
    )
    with op.batch_alter_table("contexto_uso", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_contexto_uso_tarefa_id"), ["tarefa_id"], unique=False)

    op.create_table(
        "mensagem",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tarefa_id", sa.String(length=64), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.Column("execucao_id", sa.String(length=64), nullable=True),
        sa.Column("papel", sa.String(length=16), nullable=False),
        sa.Column("tipo", sa.String(length=32), nullable=False),
        sa.Column("conteudo", sa.Text(), nullable=False),
        sa.Column("dados", sa.JSON(), nullable=True),
        sa.Column("criado_em", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(
            ["tarefa_id"],
            ["tarefa.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("mensagem", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_mensagem_execucao_id"), ["execucao_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_mensagem_tarefa_id"), ["tarefa_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("mensagem", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_mensagem_tarefa_id"))
        batch_op.drop_index(batch_op.f("ix_mensagem_execucao_id"))
    op.drop_table("mensagem")
    with op.batch_alter_table("contexto_uso", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_contexto_uso_tarefa_id"))
    op.drop_table("contexto_uso")
