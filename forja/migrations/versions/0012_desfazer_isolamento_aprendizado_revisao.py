"""pontos de restauracao, areas isoladas, estatistica de rotas, sugestoes de memoria e utilidade da memoria

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-13 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("evento", schema=None) as b:
        b.create_index("ix_evento_execucao_seq", ["execucao_id", "seq"], unique=False)
    op.create_table(
        "ponto_restauracao",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("execucao_id", sa.String(length=64), nullable=False),
        sa.Column("tarefa_id", sa.String(length=64), nullable=False),
        sa.Column("pasta", sa.Text(), nullable=False),
        sa.Column("estado", sa.String(length=16), nullable=False),
        sa.Column("antes", sa.JSON(), nullable=False),
        sa.Column("depois", sa.JSON(), nullable=True),
        sa.Column("resumo", sa.JSON(), nullable=True),
        sa.Column("parcial", sa.Boolean(), nullable=False),
        sa.Column("criado_em", sa.String(length=40), nullable=False),
        sa.Column("finalizado_em", sa.String(length=40), nullable=True),
        sa.Column("desfeito_em", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("ponto_restauracao", schema=None) as b:
        b.create_index(b.f("ix_ponto_restauracao_execucao_id"), ["execucao_id"], unique=False)
        b.create_index(b.f("ix_ponto_restauracao_tarefa_id"), ["tarefa_id"], unique=False)
        b.create_index(b.f("ix_ponto_restauracao_estado"), ["estado"], unique=False)
    op.create_table(
        "area_isolada",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tarefa_id", sa.String(length=64), nullable=False),
        sa.Column("pasta_origem", sa.Text(), nullable=False),
        sa.Column("caminho", sa.Text(), nullable=False),
        sa.Column("branch", sa.String(length=200), nullable=False),
        sa.Column("estado", sa.String(length=16), nullable=False),
        sa.Column("criado_em", sa.String(length=40), nullable=False),
        sa.Column("removida_em", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("area_isolada", schema=None) as b:
        b.create_index(b.f("ix_area_isolada_tarefa_id"), ["tarefa_id"], unique=False)
        b.create_index(b.f("ix_area_isolada_estado"), ["estado"], unique=False)
    op.create_table(
        "estatistica_rota",
        sa.Column("chave", sa.String(length=200), nullable=False),
        sa.Column("nivel", sa.String(length=16), nullable=False),
        sa.Column("parte", sa.String(length=32), nullable=False),
        sa.Column("modelo", sa.String(length=120), nullable=False),
        sa.Column("execucoes", sa.Integer(), nullable=False),
        sa.Column("sucessos", sa.Integer(), nullable=False),
        sa.Column("taxa", sa.Float(), nullable=False),
        sa.Column("atualizado_em", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("chave"),
    )
    with op.batch_alter_table("estatistica_rota", schema=None) as b:
        b.create_index(b.f("ix_estatistica_rota_nivel"), ["nivel"], unique=False)
    op.create_table(
        "sugestao_memoria",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tipo", sa.String(length=24), nullable=False),
        sa.Column("chave", sa.String(length=200), nullable=False),
        sa.Column("memorias", sa.JSON(), nullable=False),
        sa.Column("namespace", sa.String(length=200), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("dados", sa.JSON(), nullable=True),
        sa.Column("estado", sa.String(length=16), nullable=False),
        sa.Column("criado_em", sa.String(length=40), nullable=False),
        sa.Column("decidido_em", sa.String(length=40), nullable=True),
        sa.Column("decidido_por", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chave"),
    )
    with op.batch_alter_table("sugestao_memoria", schema=None) as b:
        b.create_index(b.f("ix_sugestao_memoria_tipo"), ["tipo"], unique=False)
        b.create_index(b.f("ix_sugestao_memoria_namespace"), ["namespace"], unique=False)
        b.create_index(b.f("ix_sugestao_memoria_estado"), ["estado"], unique=False)
    with op.batch_alter_table("memoria", schema=None) as b:
        b.add_column(sa.Column("usos", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("ultimo_uso", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("memoria", schema=None) as b:
        b.drop_column("ultimo_uso")
        b.drop_column("usos")
    op.drop_table("sugestao_memoria")
    op.drop_table("estatistica_rota")
    op.drop_table("area_isolada")
    op.drop_table("ponto_restauracao")
    with op.batch_alter_table("evento", schema=None) as b:
        b.drop_index("ix_evento_execucao_seq")
