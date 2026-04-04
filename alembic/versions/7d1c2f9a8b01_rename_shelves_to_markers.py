"""rename_shelves_to_markers

Revision ID: 7d1c2f9a8b01
Revises: 9c7c5d9dddea
Create Date: 2026-01-23 23:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d1c2f9a8b01'
down_revision: Union[str, Sequence[str], None] = '9c7c5d9dddea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Rename tables
    op.rename_table('shelves', 'markers')
    op.rename_table('paper_shelves', 'paper_markers')

    # Rename column in join table
    with op.batch_alter_table('paper_markers', schema=None) as batch_op:
        batch_op.alter_column('shelf_id', new_column_name='marker_id', existing_type=sa.String(length=36))


def downgrade() -> None:
    """Downgrade schema."""
    # Rename column back
    with op.batch_alter_table('paper_markers', schema=None) as batch_op:
        batch_op.alter_column('marker_id', new_column_name='shelf_id', existing_type=sa.String(length=36))

    # Rename tables back
    op.rename_table('paper_markers', 'paper_shelves')
    op.rename_table('markers', 'shelves')
