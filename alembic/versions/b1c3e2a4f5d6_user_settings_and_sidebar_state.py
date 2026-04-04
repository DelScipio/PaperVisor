"""user settings and sidebar state

Revision ID: b1c3e2a4f5d6
Revises: 2b9a6c1f4d2a, 4f7c1a0d2b3c, 6d4a7c6f8c2a
Create Date: 2026-01-05

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c3e2a4f5d6'
down_revision: Union[str, Sequence[str], None] = (
    '2b9a6c1f4d2a',
    '4f7c1a0d2b3c',
    '6d4a7c6f8c2a',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'user_settings' not in existing_tables:
        op.create_table(
            'user_settings',
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('key', sa.String(length=64), nullable=False),
            sa.Column('value', sa.String(length=2048), nullable=False, server_default=''),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('user_id', 'key', name='pk_user_settings'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        )


def downgrade() -> None:
    op.drop_table('user_settings')
