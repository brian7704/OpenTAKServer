"""Added data sync tables

Revision ID: 5d06227dea50
Revises: 6af2256c568d
Create Date: 2024-10-09 14:35:53.352679

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5d06227dea50'
down_revision = '6af2256c568d'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('mission_content',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('keywords', sa.JSON(), nullable=True),
    sa.Column('mime_type', sa.String(), nullable=True),
    sa.Column('name', sa.String(), nullable=True),
    sa.Column('submission_time', sa.DateTime(), nullable=True),
    sa.Column('submitter', sa.String(), nullable=True),
    sa.Column('uid', sa.String(), nullable=True),
    sa.Column('creator_uid', sa.String(), nullable=True),
    sa.Column('hash', sa.String(), nullable=True),
    sa.Column('size', sa.Integer(), nullable=True),
    sa.Column('expiration', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('missions',
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('description', sa.String(), nullable=True),
    sa.Column('chat_room', sa.String(), nullable=True),
    sa.Column('base_layer', sa.String(), nullable=True),
    sa.Column('bbox', sa.String(), nullable=True),
    sa.Column('path', sa.String(), nullable=True),
    sa.Column('classification', sa.String(), nullable=True),
    sa.Column('tool', sa.String(), nullable=True),
    sa.Column('group_name', sa.String(), nullable=True),
    sa.Column('default_role', sa.String(), nullable=True),
    sa.Column('keywords', sa.JSON(), nullable=True),
    sa.Column('creator_uid', sa.String(), nullable=True),
    sa.Column('create_time', sa.Integer(), nullable=True),
    sa.Column('external_data', sa.JSON(), nullable=True),
    sa.Column('feeds', sa.JSON(), nullable=True),
    sa.Column('map_layers', sa.JSON(), nullable=True),
    sa.Column('invite_only', sa.Boolean(), nullable=True),
    sa.Column('expiration', sa.Integer(), nullable=False),
    sa.Column('guid', sa.String(), nullable=True),
    sa.Column('password_protected', sa.Boolean(), nullable=True),
    sa.Column('password', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('name')
    )
    op.create_table('mission_changes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('isFederatedChange', sa.Boolean(), nullable=False),
    sa.Column('change_type', sa.String(), nullable=False),
    sa.Column('mission_name', sa.String(), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.Column('creator_uid', sa.String(), nullable=False),
    sa.Column('server_time', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['mission_name'], ['missions.name'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('mission_content_mission',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('mission_content_id', sa.Integer(), nullable=False),
    sa.Column('mission_name', sa.String(), nullable=False),
    sa.ForeignKeyConstraint(['mission_content_id'], ['mission_content.id'], ),
    sa.ForeignKeyConstraint(['mission_name'], ['missions.name'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('mission_invitations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('mission_name', sa.String(), nullable=False),
    sa.Column('client_uid', sa.String(), nullable=False),
    sa.ForeignKeyConstraint(['mission_name'], ['missions.name'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('mission_roles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('clientUid', sa.String(), nullable=False),
    sa.Column('username', sa.String(), nullable=False),
    sa.Column('createTime', sa.DateTime(), nullable=False),
    sa.Column('role_type', sa.String(), nullable=False),
    sa.Column('mission_name', sa.String(), nullable=False),
    sa.ForeignKeyConstraint(['mission_name'], ['missions.name'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('mission_content_mission_changes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('mission_content_id', sa.Integer(), nullable=False),
    sa.Column('mission_change_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['mission_change_id'], ['mission_changes.id'], ),
    sa.ForeignKeyConstraint(['mission_content_id'], ['mission_content.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('mission_content_mission_changes')
    op.drop_table('mission_roles')
    op.drop_table('mission_invitations')
    op.drop_table('mission_content_mission')
    op.drop_table('mission_changes')
    op.drop_table('missions')
    op.drop_table('mission_content')
    # ### end Alembic commands ###
