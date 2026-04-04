"""add paper lookup indexes

Adds missing indexes used by common search/sort patterns:
- papers.doi
- papers.isbn
- papers.last_opened_at

Revision ID: e3c7b1a9d2f4
Revises: 9a325a988a02a49b
Create Date: 2026-01-31

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = 'e3c7b1a9d2f4'
down_revision = '9a325a988a02a49b'
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
    _create_index_if_missing('ix_papers_doi', 'papers', ['doi'])
    _create_index_if_missing('ix_papers_isbn', 'papers', ['isbn'])
    _create_index_if_missing('ix_papers_last_opened_at', 'papers', ['last_opened_at'])


def downgrade() -> None:
    # Best-effort drops; ignore if missing.
    for name in [
        'ix_papers_last_opened_at',
        'ix_papers_isbn',
        'ix_papers_doi',
    ]:
        try:
            op.drop_index(name)
        except Exception:
            pass
