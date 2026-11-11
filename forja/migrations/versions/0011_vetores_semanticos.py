"""vetores da busca semantica opcional (inativa por padrao)
Revision ID: 0011
Revises: 0010
Create Date: 2026-11-12 10:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vetor_semantico",
        sa.Column("chave", sa.String(length=80), nullable=False),
        sa.Column("origem", sa.String(length=16), nullable=False),
        sa.Column("ref", sa.String(length=64), nullable=False),
        sa.Column("namespace", sa.String(length=200), nullable=False),
        sa.Column("sha", sa.String(length=64), nullable=False),
        sa.Column("modelo", sa.String(length=120), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("vetor", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("chave"),
    )
    with op.batch_alter_table("vetor_semantico", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_vetor_semantico_origem"), ["origem"], unique=False)
        batch_op.create_index(batch_op.f("ix_vetor_semantico_ref"), ["ref"], unique=False)
        batch_op.create_index(batch_op.f("ix_vetor_semantico_namespace"), ["namespace"], unique=False)
        batch_op.create_index(batch_op.f("ix_vetor_semantico_modelo"), ["modelo"], unique=False)


def downgrade() -> None:
    op.drop_table("vetor_semantico")
