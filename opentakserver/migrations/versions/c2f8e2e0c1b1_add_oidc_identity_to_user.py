"""add oidc identity to user

Revision ID: c2f8e2e0c1b1
Revises: 6a7929c07690
Create Date: 2026-04-10 20:45:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c2f8e2e0c1b1"
down_revision = "6a7929c07690"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(sa.Column("oidc_issuer", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("oidc_subject", sa.String(length=255), nullable=True))
        batch_op.create_unique_constraint("uq_user_oidc_identity", ["oidc_issuer", "oidc_subject"])


def downgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_constraint("uq_user_oidc_identity", type_="unique")
        batch_op.drop_column("oidc_subject")
        batch_op.drop_column("oidc_issuer")
