"""initial FLD schema (Postgres + pgvector)

Revision ID: 0001
Revises:
Create Date: baseline

ponytail: Baseline erzeugt das komplette Schema via metadata.create_all statt per-Tabelle-Ops —
deterministisch und importfrei für den pgvector-Typ. Folge-Migrationen laufen normal per Autogenerate.
"""
from alembic import op

from fldos.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
