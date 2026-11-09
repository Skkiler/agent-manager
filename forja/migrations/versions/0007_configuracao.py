"""configuracao do orquestrador

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-09 18:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "configuracao",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("valor", sa.JSON(), nullable=False),
        sa.Column("versao", sa.Integer(), nullable=False),
        sa.Column("atualizado_em", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("configuracao")
