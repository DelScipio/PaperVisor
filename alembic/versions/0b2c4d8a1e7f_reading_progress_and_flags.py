"""reading progress and flags

Revision ID: 0b2c4d8a1e7f
Revises: de9e5d42159e
Create Date: 2026-01-05

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0b2c4d8a1e7f'
down_revision: Union[str, Sequence[str], None] = 'de9e5d42159e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('papers', sa.Column('reading_progress', sa.Float(), nullable=False, server_default='0'))
    op.add_column('papers', sa.Column('reading_location', sa.String(length=2048), nullable=False, server_default=''))
    op.add_column('papers', sa.Column('is_completed', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('papers', sa.Column('is_favorite', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('papers', 'is_favorite')
    op.drop_column('papers', 'is_completed')
    op.drop_column('papers', 'reading_location')
    op.drop_column('papers', 'reading_progress')
