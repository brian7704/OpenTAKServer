"""Added certificate revocation

Revision ID: c4f1e2a9b7d3
Revises: 434be4e1896a
Create Date: 2026-10-29 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c4f1e2a9b7d3"
down_revision = "434be4e1896a"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "revoked_certificates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("serial_number", sa.String(length=64), nullable=False),
        sa.Column("common_name", sa.String(length=255), nullable=True),
        sa.Column("eud_uid", sa.String(length=255), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_by", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("serial_number"),
    )

    with op.batch_alter_table("certificates", schema=None) as batch_op:
        batch_op.add_column(sa.Column("serial_number", sa.String(length=64), nullable=True))


def downgrade():
    with op.batch_alter_table("certificates", schema=None) as batch_op:
        batch_op.drop_column("serial_number")

    op.drop_table("revoked_certificates")
