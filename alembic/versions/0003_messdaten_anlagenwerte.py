"""Messdaten der Anlage (Schattenbetrieb) + plant_config (fehlte bisher in den Migrationen)

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    have = sa.inspect(op.get_bind()).get_table_names()
    if "plant_config" not in have:  # lokal per Hand entstanden, neue Installationen hatten sie nicht
        op.create_table(
            "plant_config",
            sa.Column("tenant_id", sa.String(64), primary_key=True),
            sa.Column("params", sa.JSON, nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if "plant_measurements" in have:  # frische DB: 0001 legt per create_all schon das aktuelle Modell an
        return
    op.create_table(
        "plant_measurements",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("p_mw", sa.Float, nullable=False),
        sa.UniqueConstraint("tenant_id", "ts", name="uq_plant_measurements"),
    )


def downgrade() -> None:
    op.drop_table("plant_measurements")
