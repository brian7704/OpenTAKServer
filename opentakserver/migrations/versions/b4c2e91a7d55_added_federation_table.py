"""Added federation table

Revision ID: b4c2e91a7d55
Revises: 00442761c803
Create Date: 2026-07-17 20:15:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b4c2e91a7d55"
down_revision = "00442761c803"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "federation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("protocol_version", sa.Integer(), nullable=False),
        sa.Column("outbound", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("reconnect_interval", sa.Integer(), nullable=True),
        sa.Column("cert_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("cert_common_name", sa.String(length=255), nullable=True),
        sa.Column("inbound_groups", sa.JSON(), nullable=True),
        sa.Column("outbound_groups", sa.JSON(), nullable=True),
        sa.Column("last_connected", sa.DateTime(), nullable=True),
        sa.Column("last_disconnected", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("cert_fingerprint"),
    )


def downgrade():
    op.drop_table("federation")
