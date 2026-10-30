"""Reserve je Viertelstunde im Fahrplan (Review H-05) + vor der Auktion erwarteter Mehrerlös je Backtest-Tag (H-06)

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

NEW = {"dispatch": ("reserve_up_mw", "reserve_down_mw"), "backtest_results": ("exp_fc",)}


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    for table, cols in NEW.items():
        have = {c["name"] for c in insp.get_columns(table)}  # frische DB: 0001 legt per create_all schon alles an
        for c in cols:
            if c not in have:
                op.add_column(table, sa.Column(c, sa.Float, nullable=True))


def downgrade() -> None:
    for table, cols in NEW.items():
        for c in cols:
            op.drop_column(table, c)
