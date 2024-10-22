"""Added mission_name to cot table

Revision ID: d31bff4a15c7
Revises: 5d06227dea50
Create Date: 2024-10-09 15:40:49.385642

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd31bff4a15c7'
down_revision = '5d06227dea50'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('cot', schema=None) as batch_op:
        batch_op.add_column(sa.Column('mission_name', sa.String(), nullable=True))
        batch_op.create_foreign_key("mission_name", 'missions', ['mission_name'], ['name'])

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('cot', schema=None) as batch_op:
        batch_op.drop_constraint("mission_name", type_='foreignkey')
        batch_op.drop_column('mission_name')

    # ### end Alembic commands ###