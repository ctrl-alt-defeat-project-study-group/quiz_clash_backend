"""add auth roles email tokens and ownership

Revision ID: 492ae13d2c1a
Revises: ec282c1f387b
Create Date: 2026-11-20 20:58:05.306842

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '492ae13d2c1a'
down_revision: Union[str, None] = 'ec282c1f387b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'email_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('purpose', sa.String(length=20), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_email_tokens_user_id_users', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('email_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_email_tokens_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_email_tokens_token_hash'), ['token_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_email_tokens_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('attempts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_attempts_user_id'), ['user_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_attempts_user_id_users', 'users', ['user_id'], ['id'], ondelete='CASCADE'
        )

    with op.batch_alter_table('quizzes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_quizzes_owner_id'), ['owner_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_quizzes_owner_id_users', 'users', ['owner_id'], ['id'], ondelete='CASCADE'
        )

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('display_name', sa.String(length=100), nullable=False, server_default='User')
        )
        batch_op.add_column(
            sa.Column('role', sa.String(length=20), nullable=False, server_default='user')
        )
        batch_op.add_column(
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('email_verified_at')
        batch_op.drop_column('is_active')
        batch_op.drop_column('role')
        batch_op.drop_column('display_name')

    with op.batch_alter_table('quizzes', schema=None) as batch_op:
        batch_op.drop_constraint('fk_quizzes_owner_id_users', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_quizzes_owner_id'))
        batch_op.drop_column('owner_id')

    with op.batch_alter_table('attempts', schema=None) as batch_op:
        batch_op.drop_constraint('fk_attempts_user_id_users', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_attempts_user_id'))
        batch_op.drop_column('user_id')

    with op.batch_alter_table('email_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_email_tokens_user_id'))
        batch_op.drop_index(batch_op.f('ix_email_tokens_token_hash'))
        batch_op.drop_index(batch_op.f('ix_email_tokens_id'))

    op.drop_table('email_tokens')
