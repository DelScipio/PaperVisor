"""merge heads (user favorites)

Revision ID: 2a6d4c7e9b11
Revises: 1f3a8b9c2d10, 2432924dd596
Create Date: 2026-01-06

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '2a6d4c7e9b11'
down_revision: Union[str, Sequence[str], None] = ('1f3a8b9c2d10', '2432924dd596')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
