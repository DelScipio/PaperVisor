"""add_updated_at_to_papers

Revision ID: 9c7c5d9dddea
Revises: ab12cd34ef56
Create Date: 2026-01-22 22:35:32.852809

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c7c5d9dddea'
down_revision: Union[str, Sequence[str], None] = 'ab12cd34ef56' # Point to previous HEAD
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('papers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))

    # Populate existing rows?
    op.execute("UPDATE papers SET updated_at = created_at WHERE updated_at IS NULL")

    # Set nullable=False now that data is filled
    with op.batch_alter_table('papers', schema=None) as batch_op:
        batch_op.alter_column('updated_at', nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('papers', schema=None) as batch_op:
        batch_op.drop_column('updated_at')
