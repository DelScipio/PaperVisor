"""sharing_global

Revision ID: f0795835d5ed
Revises: d3e4f5a6b7c8
Create Date: 2026-02-22 00:26:37.336928

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f0795835d5ed'
down_revision: Union[str, Sequence[str], None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('hidden_global_libraries',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('library_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['library_id'], ['libraries.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'library_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('hidden_global_libraries')
