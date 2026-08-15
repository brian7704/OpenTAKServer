"""altered foreign key on device_profiles

Revision ID: 6a7929c07690
Revises: 591a98184047
Create Date: 2026-02-20 23:36:36.134346

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "6a7929c07690"
down_revision = "591a98184047"
branch_labels = None
depends_on = None


def _eud_uid_foreign_keys():
    """Return the deployed names of foreign keys on device_profiles.eud_uid.

    Older PostgreSQL installations may have an automatically generated
    ``device_profiles_eud_uid_fkey`` name, while fresh OTS databases use the
    explicit ``eud_uid`` name from revision 61c7cfea0c86.  Alembic migrations
    must handle both histories.
    """
    inspector = sa.inspect(op.get_bind())
    return [
        foreign_key["name"]
        for foreign_key in inspector.get_foreign_keys("device_profiles")
        if foreign_key.get("name")
        and foreign_key.get("constrained_columns") == ["eud_uid"]
    ]


def upgrade():
    constraint_names = _eud_uid_foreign_keys()
    with op.batch_alter_table("device_profiles", schema=None) as batch_op:
        for constraint_name in constraint_names:
            batch_op.drop_constraint(constraint_name, type_="foreignkey")


def downgrade():
    if _eud_uid_foreign_keys():
        return

    with op.batch_alter_table("device_profiles", schema=None) as batch_op:
        batch_op.create_foreign_key("eud_uid", "euds", ["eud_uid"], ["uid"])
