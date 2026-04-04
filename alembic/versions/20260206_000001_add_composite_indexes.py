"""add composite indexes for common filter patterns

Adds indexes that cover frequent query patterns not yet indexed:
  - Paper(library_id, file_type)       – library + type filter
  - Paper(file_type, is_completed)     – completed-papers filter
  - Marker(owner_user_id, visibility)  – user-visible markers
  - PaperMarker(marker_id, paper_id)   – marker ↔ paper lookup (both directions)

Revision ID: a1b2c3d4e5f6
Revises: f6a1d4c9b0e2
Create Date: 2026-02-06

"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'f6a1d4c9b0e2'
branch_labels = None
depends_on = None


def _create_index_if_missing(name: str, table: str, cols: list[str]) -> None:
    """Create an index, using IF NOT EXISTS where supported."""
    bind = op.get_bind()
    dialect = getattr(getattr(bind, 'dialect', None), 'name', '')

    cols_sql = ', '.join(cols)

    if dialect == 'sqlite':
        op.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols_sql})')
        return

    try:
        op.create_index(name, table, cols)
    except Exception:
        try:
            op.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols_sql})')
        except Exception:
            pass


def upgrade() -> None:
    # Library + type filter (e.g. "all books in library X").
    _create_index_if_missing('ix_papers_library_id_file_type', 'papers', ['library_id', 'file_type'])

    # Completed papers filter (e.g. "all completed books").
    _create_index_if_missing('ix_papers_file_type_is_completed', 'papers', ['file_type', 'is_completed'])

    # User markers listing (filtered by owner + visibility).
    _create_index_if_missing('ix_markers_owner_visibility', 'markers', ['owner_user_id', 'visibility'])

    # Marker ↔ paper composite (covering index for the junction table).
    _create_index_if_missing('ix_paper_markers_marker_paper', 'paper_markers', ['marker_id', 'paper_id'])


def downgrade() -> None:
    for name in [
        'ix_paper_markers_marker_paper',
        'ix_markers_owner_visibility',
        'ix_papers_file_type_is_completed',
        'ix_papers_library_id_file_type',
    ]:
        try:
            op.drop_index(name)
        except Exception:
            pass
