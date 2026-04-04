"""app_settings

Revision ID: 9c1dfb6c0a1e
Revises: 6d4a7c6f8c2a
Create Date: 2026-01-04

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9c1dfb6c0a1e'
down_revision = '6d4a7c6f8c2a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'app_settings' not in existing_tables:
        op.create_table(
            'app_settings',
            sa.Column('key', sa.String(length=64), primary_key=True),
            sa.Column('value', sa.String(length=2048), nullable=False, server_default=''),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    op.drop_table('app_settings')
