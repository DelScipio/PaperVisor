"""patterns

Revision ID: 6d4a7c6f8c2a
Revises: a7c5f34073f3
Create Date: 2026-01-04

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6d4a7c6f8c2a'
down_revision = 'a7c5f34073f3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'naming_patterns' not in existing_tables:
        op.create_table(
            'naming_patterns',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('key', sa.String(length=64), nullable=False, unique=True),
            sa.Column('pattern', sa.String(length=1024), nullable=False, server_default=''),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        )

    if 'library_naming_patterns' not in existing_tables:
        op.create_table(
            'library_naming_patterns',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('library_id', sa.String(length=36), nullable=False, unique=True),
            sa.Column('pattern', sa.String(length=1024), nullable=False, server_default=''),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['library_id'], ['libraries.id'], ondelete='CASCADE'),
        )


def downgrade() -> None:
    op.drop_table('library_naming_patterns')
    op.drop_table('naming_patterns')
