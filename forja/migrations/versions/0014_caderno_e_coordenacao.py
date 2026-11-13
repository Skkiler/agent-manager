"""caderno da tarefa (contexto fora da janela) e coordenacao (master/sub-masters)

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-15 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "caderno_item",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tarefa_id", sa.String(length=64), nullable=False),
        sa.Column("execucao_id", sa.String(length=64), nullable=True),
        sa.Column("tipo", sa.String(length=16), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("ref", sa.String(length=200), nullable=False),
        sa.Column("origem", sa.String(length=32), nullable=False),
        sa.Column("criado_em", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("caderno_item", schema=None) as b:
        b.create_index(b.f("ix_caderno_item_tarefa_id"), ["tarefa_id"], unique=False)
    op.create_table(
        "coordenacao",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tipo", sa.String(length=16), nullable=False),
        sa.Column("pai_id", sa.String(length=64), nullable=True),
        sa.Column("projeto_id", sa.String(length=64), nullable=True),
        sa.Column("titulo", sa.String(length=200), nullable=False),
        sa.Column("objetivo", sa.Text(), nullable=False),
        sa.Column("estado", sa.String(length=16), nullable=False),
        sa.Column("chamadas_usadas", sa.Integer(), nullable=False),
        sa.Column("max_chamadas", sa.Integer(), nullable=False),
        sa.Column("criado_em", sa.String(length=40), nullable=False),
        sa.Column("atualizado_em", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("coordenacao", schema=None) as b:
        b.create_index(b.f("ix_coordenacao_tipo"), ["tipo"], unique=False)
        b.create_index(b.f("ix_coordenacao_pai_id"), ["pai_id"], unique=False)
        b.create_index(b.f("ix_coordenacao_estado"), ["estado"], unique=False)
    op.create_table(
        "mensagem_coordenacao",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("coordenacao_id", sa.String(length=64), nullable=False),
        sa.Column("papel", sa.String(length=16), nullable=False),
        sa.Column("conteudo", sa.Text(), nullable=False),
        sa.Column("dados", sa.JSON(), nullable=True),
        sa.Column("tarefa_id", sa.String(length=64), nullable=True),
        sa.Column("criado_em", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("mensagem_coordenacao", schema=None) as b:
        b.create_index(b.f("ix_mensagem_coordenacao_coordenacao_id"), ["coordenacao_id"], unique=False)


def downgrade() -> None:
    op.drop_table("mensagem_coordenacao")
    op.drop_table("coordenacao")
    op.drop_table("caderno_item")
