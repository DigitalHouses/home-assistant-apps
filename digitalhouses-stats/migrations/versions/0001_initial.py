"""Initial telemetry schema."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "installations",
        sa.Column("product", sa.Text(), nullable=False),
        sa.Column(
            "installation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("installation_token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("product", "installation_id"),
    )

    op.create_table(
        "heartbeats",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("product", sa.Text(), nullable=False),
        sa.Column(
            "installation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("telemetry_policy_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["product", "installation_id"],
            ["installations.product", "installations.installation_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_heartbeats_received_at",
        "heartbeats",
        ["received_at"],
    )
    op.create_index(
        "ix_heartbeats_product_installation_received_at",
        "heartbeats",
        ["product", "installation_id", "received_at"],
    )
    op.create_index(
        "ix_heartbeats_product_version_received_at",
        "heartbeats",
        ["product", "version", "received_at"],
    )
    op.create_index(
        "ix_heartbeats_country_received_at",
        "heartbeats",
        ["country", "received_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_heartbeats_country_received_at", table_name="heartbeats")
    op.drop_index(
        "ix_heartbeats_product_version_received_at",
        table_name="heartbeats",
    )
    op.drop_index(
        "ix_heartbeats_product_installation_received_at",
        table_name="heartbeats",
    )
    op.drop_index("ix_heartbeats_received_at", table_name="heartbeats")
    op.drop_table("heartbeats")
    op.drop_table("installations")
