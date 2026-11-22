"""widen live_rooms.pin for account+topic room codes

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-22 13:48:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("live_rooms", schema=None) as batch_op:
        batch_op.alter_column(
            "pin",
            existing_type=sa.String(length=6),
            type_=sa.String(length=16),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("live_rooms", schema=None) as batch_op:
        batch_op.alter_column(
            "pin",
            existing_type=sa.String(length=16),
            type_=sa.String(length=6),
            existing_nullable=False,
        )
