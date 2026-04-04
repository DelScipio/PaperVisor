"""merge heads

Revision ID: 098cf0bded5a
Revises: 4a1b8c9d0e11, f2c7a1b4d9e0
Create Date: 2026-01-07 00:53:03.578010

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '098cf0bded5a'
down_revision: Union[str, Sequence[str], None] = ('4a1b8c9d0e11', 'f2c7a1b4d9e0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
