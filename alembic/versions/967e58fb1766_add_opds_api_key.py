"""add_opds_api_key

Revision ID: 967e58fb1766
Revises: 7d1c2f9a8b01
Create Date: 2026-01-24 13:12:43.956589

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '967e58fb1766'
down_revision: Union[str, Sequence[str], None] = '7d1c2f9a8b01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add opds_api_key column to users table
    op.add_column('users', sa.Column('opds_api_key', sa.String(length=32), nullable=True))
    op.create_index(op.f('ix_users_opds_api_key'), 'users', ['opds_api_key'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_users_opds_api_key'), table_name='users')
    op.drop_column('users', 'opds_api_key')

