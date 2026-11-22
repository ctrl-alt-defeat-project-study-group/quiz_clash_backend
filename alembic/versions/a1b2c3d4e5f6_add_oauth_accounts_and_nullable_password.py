"""add oauth accounts and nullable password

Revision ID: a1b2c3d4e5f6
Revises: 9e4b2c7a1d53
Create Date: 2026-11-22 10:52:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "9e4b2c7a1d53"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "password_hash",
            existing_type=sa.String(length=255),
            nullable=True,
        )
        batch_op.add_column(sa.Column("avatar_url", sa.String(length=500), nullable=True))

    op.create_table(
        "oauth_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column("provider_email", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_oauth_accounts_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
        sa.UniqueConstraint("user_id", "provider", name="uq_oauth_user_provider"),
    )
    with op.batch_alter_table("oauth_accounts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_oauth_accounts_id"), ["id"], unique=False)
        batch_op.create_index(batch_op.f("ix_oauth_accounts_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_oauth_accounts_provider"), ["provider"], unique=False)


def downgrade() -> None:
    op.drop_table("oauth_accounts")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("avatar_url")
        batch_op.alter_column(
            "password_hash",
            existing_type=sa.String(length=255),
            nullable=False,
        )
