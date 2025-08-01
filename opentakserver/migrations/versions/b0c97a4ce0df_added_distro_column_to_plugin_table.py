"""Added distro column to plugin table

Revision ID: b0c97a4ce0df
Revises: f310052349cb
Create Date: 2025-05-02 21:27:56.708927

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b0c97a4ce0df'
down_revision = 'f310052349cb'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('plugins', schema=None) as batch_op:
        batch_op.add_column(sa.Column('distro', sa.String(length=255), nullable=False))
        batch_op.create_unique_constraint("distro", ['distro'])

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('plugins', schema=None) as batch_op:
        batch_op.drop_constraint("distro", type_='unique')
        batch_op.drop_column('distro')

    # ### end Alembic commands ###
