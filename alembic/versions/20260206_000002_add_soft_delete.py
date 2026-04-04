"""add soft delete for papers

Adds a ``deleted_at`` column to the ``papers`` table.
When non-NULL the paper is considered "in trash" and excluded from
normal queries.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-06

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('papers', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))

    # Index for fast trash listing / filtering.
    bind = op.get_bind()
    dialect = getattr(getattr(bind, 'dialect', None), 'name', '')
    if dialect == 'sqlite':
        op.execute('CREATE INDEX IF NOT EXISTS ix_papers_deleted_at ON papers (deleted_at)')
    else:
        try:
            op.create_index('ix_papers_deleted_at', 'papers', ['deleted_at'])
        except Exception:
            pass


def downgrade() -> None:
    try:
        op.drop_index('ix_papers_deleted_at')
    except Exception:
        pass
    op.drop_column('papers', 'deleted_at')
