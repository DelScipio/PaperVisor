"""open counts and last opened/read

Revision ID: 2b9a6c1f4d2a
Revises: 0b2c4d8a1e7f
Create Date: 2026-01-05

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b9a6c1f4d2a'
down_revision: Union[str, Sequence[str], None] = '0b2c4d8a1e7f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('papers', sa.Column('open_count_total', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('papers', sa.Column('open_count_since_reset', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('papers', sa.Column('open_count_reset_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('papers', sa.Column('last_opened_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('papers', sa.Column('last_read_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('papers', 'last_read_at')
    op.drop_column('papers', 'last_opened_at')
    op.drop_column('papers', 'open_count_reset_at')
    op.drop_column('papers', 'open_count_since_reset')
    op.drop_column('papers', 'open_count_total')
