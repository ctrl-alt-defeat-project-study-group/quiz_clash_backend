"""phase7 and 8 live rooms and user settings

Revision ID: 9e4b2c7a1d53
Revises: 7c3a1f9e4b20
Create Date: 2026-11-20 23:52:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9e4b2c7a1d53'
down_revision: Union[str, None] = '7c3a1f9e4b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'live_rooms',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('quiz_id', sa.Integer(), nullable=False),
        sa.Column('host_id', sa.Integer(), nullable=False),
        sa.Column('pin', sa.String(length=6), nullable=False),
        sa.Column('timer_seconds', sa.Integer(), nullable=False, server_default='20'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='lobby'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['host_id'], ['users.id'], name='fk_live_rooms_host_id_users', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['quiz_id'], ['quizzes.id'], name='fk_live_rooms_quiz_id_quizzes', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('live_rooms', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_live_rooms_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_live_rooms_quiz_id'), ['quiz_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_live_rooms_host_id'), ['host_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_live_rooms_pin'), ['pin'], unique=True)

    op.create_table(
        'user_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('theme', sa.String(length=20), nullable=False, server_default='system'),
        sa.Column('ui_language', sa.String(length=10), nullable=False, server_default='en'),
        sa.Column('default_questions', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('difficulty', sa.String(length=30), nullable=False, server_default='Mixed'),
        sa.Column('quiz_language', sa.String(length=30), nullable=False, server_default='English'),
        sa.Column('shuffle_questions', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('show_explanations', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('study_reminders', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('weekly_summary', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_user_settings_user_id_users', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_settings_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_settings_user_id'), ['user_id'], unique=True)


def downgrade() -> None:
    op.drop_table('user_settings')
    op.drop_table('live_rooms')
