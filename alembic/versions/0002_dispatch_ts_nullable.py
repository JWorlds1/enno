"""dispatch.ts nullable machen (konsistent mit API/Repository)

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("dispatch", "ts", nullable=True)


def downgrade() -> None:
    op.alter_column("dispatch", "ts", nullable=False)
