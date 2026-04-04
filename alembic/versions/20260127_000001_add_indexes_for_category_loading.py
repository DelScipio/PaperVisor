"""add indexes for category loading

Revision ID: c1a2b3c4d5e6
Revises: 967e58fb1766
Create Date: 2026-01-27

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = 'c1a2b3c4d5e6'
down_revision = '967e58fb1766'
branch_labels = None
depends_on = None


def _create_index_if_missing(name: str, table: str, cols: list[str]) -> None:
    """Create an index, using IF NOT EXISTS where supported.

    We prefer idempotent SQL here because some installs may already have
    partial indexes (or old migrations may have been applied).
    """

    bind = op.get_bind()
    dialect = getattr(getattr(bind, 'dialect', None), 'name', '')

    cols_sql = ', '.join(cols)

    if dialect == 'sqlite':
        op.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols_sql})')
        return

    # Postgres supports IF NOT EXISTS, but Alembic's op.create_index does not.
    # For other DBs, attempt normal create.
    try:
        op.create_index(name, table, cols)
    except Exception:
        # Fallback to raw SQL when possible.
        try:
            op.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols_sql})')
        except Exception:
            # If the index already exists (or DB doesn't support IF NOT EXISTS), ignore.
            pass


def upgrade() -> None:
    # Speeds up Library views and most list sorts.
    _create_index_if_missing('ix_papers_library_id', 'papers', ['library_id'])
    _create_index_if_missing('ix_papers_created_at', 'papers', ['created_at'])

    # Speeds up Marker/Shelf category loads (queries filter by marker_id).
    _create_index_if_missing('ix_paper_markers_marker_id', 'paper_markers', ['marker_id'])

    # Speeds up tag filtering (queries filter by tag_id).
    _create_index_if_missing('ix_paper_tags_tag_id', 'paper_tags', ['tag_id'])

    # Speeds up permission checks on every file request.
    # Pattern: WHERE library_id=? AND shared_with_user_id=? AND status='accepted'
    _create_index_if_missing('ix_library_shares_lib_user_status', 'library_shares', ['library_id', 'shared_with_user_id', 'status'])
    # Pattern: inbox / listings often filter by user+status.
    _create_index_if_missing('ix_library_shares_with_user_status', 'library_shares', ['shared_with_user_id', 'status'])


def downgrade() -> None:
    # Best-effort drops; ignore if missing.
    for name in [
        'ix_paper_tags_tag_id',
        'ix_paper_markers_marker_id',
        'ix_papers_created_at',
        'ix_papers_library_id',
    ]:
        try:
            op.drop_index(name)
        except Exception:
            pass
