"""clear legacy smart shelf rules

Revision ID: ab12cd34ef56
Revises: 4f7c1a0d2b3c, eddc6972370f
Create Date: 2026-01-11

This is a data migration.
- Drops legacy smart-shelf rule JSON by clearing `shelves.rules_json` for all smart shelves.
- Resets scope to 'all'.

After this migration, smart shelves without rules match nothing until configured.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ab12cd34ef56'
down_revision: Union[str, Sequence[str], None] = ('4f7c1a0d2b3c', 'eddc6972370f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE shelves SET rules_json = '', scope = 'all' WHERE is_smart = true"))


def downgrade() -> None:
    # Cannot restore prior JSON rules.
    pass
