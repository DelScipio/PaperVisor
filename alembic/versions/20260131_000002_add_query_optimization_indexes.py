"""add query optimization indexes

Adds composite indexes for common list patterns.

Revision ID: f6a1d4c9b0e2
Revises: e3c7b1a9d2f4
Create Date: 2026-01-31

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = 'f6a1d4c9b0e2'
down_revision = 'e3c7b1a9d2f4'
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
    # Common pattern: filter by library then sort by created/last opened.
    _create_index_if_missing('ix_papers_library_id_created_at', 'papers', ['library_id', 'created_at'])
    _create_index_if_missing('ix_papers_library_id_last_opened_at', 'papers', ['library_id', 'last_opened_at'])

    # Favorites / To-Read lists: filter by user and sort by created_at.
    _create_index_if_missing('ix_paper_favorites_user_id_created_at', 'paper_favorites', ['user_id', 'created_at'])
    _create_index_if_missing('ix_paper_to_read_user_id', 'paper_to_read', ['user_id'])
    _create_index_if_missing('ix_paper_to_read_paper_id', 'paper_to_read', ['paper_id'])
    _create_index_if_missing('ix_paper_to_read_user_id_created_at', 'paper_to_read', ['user_id', 'created_at'])


def downgrade() -> None:
    for name in [
        'ix_paper_to_read_user_id_created_at',
        'ix_paper_to_read_paper_id',
        'ix_paper_to_read_user_id',
        'ix_paper_favorites_user_id_created_at',
        'ix_papers_library_id_last_opened_at',
        'ix_papers_library_id_created_at',
    ]:
        try:
            op.drop_index(name)
        except Exception:
            pass
