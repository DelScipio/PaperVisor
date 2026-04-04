"""merge heads

Revision ID: de9e5d42159e
Revises: 86b2d2a9b1f0, 9c1dfb6c0a1e
Create Date: 2026-01-04 20:18:26.867132

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'de9e5d42159e'
down_revision: Union[str, Sequence[str], None] = ('86b2d2a9b1f0', '9c1dfb6c0a1e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
