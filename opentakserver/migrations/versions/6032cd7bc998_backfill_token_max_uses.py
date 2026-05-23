"""Backfill token max_uses

Revision ID: 6032cd7bc998
Revises: 00442761c803
Create Date: 2026-05-23 16:30:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "6032cd7bc998"
down_revision = "00442761c803"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE tokens SET max_uses = 1 WHERE max_uses IS NULL")


def downgrade():
    pass
