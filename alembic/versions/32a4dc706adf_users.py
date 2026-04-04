"""users

Revision ID: 32a4dc706adf
Revises: 2b9a6c1f4d2a
Create Date: 2026-01-05 02:28:13.562833

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '32a4dc706adf'
down_revision: Union[str, Sequence[str], None] = '2b9a6c1f4d2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('username', name='uq_users_username'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('users')
