"""phase5 api contract fields

Revision ID: 7c3a1f9e4b20
Revises: 492ae13d2c1a
Create Date: 2026-11-20 23:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c3a1f9e4b20'
down_revision: Union[str, None] = '492ae13d2c1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('quizzes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('source_filename', sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column(
                'updated_at',
                sa.DateTime(timezone=True),
                server_default=sa.text('CURRENT_TIMESTAMP'),
                nullable=True,
            )
        )
        batch_op.alter_column(
            'status',
            existing_type=sa.String(length=50),
            server_default='ready',
            existing_nullable=False,
        )

    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('explanation', sa.Text(), nullable=True))

    with op.batch_alter_table('attempts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('duration_seconds', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('attempts', schema=None) as batch_op:
        batch_op.drop_column('duration_seconds')

    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.drop_column('explanation')

    with op.batch_alter_table('quizzes', schema=None) as batch_op:
        batch_op.alter_column(
            'status',
            existing_type=sa.String(length=50),
            server_default='draft',
            existing_nullable=False,
        )
        batch_op.drop_column('updated_at')
        batch_op.drop_column('source_filename')
        batch_op.drop_column('category')
