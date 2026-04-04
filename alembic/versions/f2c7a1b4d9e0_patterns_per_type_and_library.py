"""patterns per type and library

Revision ID: f2c7a1b4d9e0
Revises: de9e5d42159e
Create Date: 2026-01-07

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2c7a1b4d9e0'
down_revision: Union[str, Sequence[str], None] = 'de9e5d42159e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite-friendly table rebuild to change unique constraint and add file_type.
    conn = op.get_bind()

    # 1) Create new table
    op.create_table(
        'library_naming_patterns_new',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column('library_id', sa.String(length=36), sa.ForeignKey('libraries.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_type', sa.String(length=16), nullable=False, server_default='paper'),
        sa.Column('pattern', sa.String(length=1024), nullable=False, server_default=''),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('library_id', 'file_type', name='uq_library_naming_patterns_library_type'),
    )

    # 2) Copy existing overrides to both types
    try:
        rows = conn.execute(sa.text('SELECT id, library_id, pattern, updated_at FROM library_naming_patterns')).fetchall()
    except Exception:
        rows = []

    for (_id, library_id, pattern, updated_at) in rows:
        for ft in ('paper', 'book'):
            conn.execute(
                sa.text(
                    'INSERT INTO library_naming_patterns_new (library_id, file_type, pattern, updated_at) '
                    'VALUES (:library_id, :file_type, :pattern, :updated_at)'
                ),
                {
                    'library_id': str(library_id),
                    'file_type': ft,
                    'pattern': str(pattern or ''),
                    'updated_at': updated_at,
                },
            )

    # 3) Swap tables
    op.drop_table('library_naming_patterns')
    op.rename_table('library_naming_patterns_new', 'library_naming_patterns')


def downgrade() -> None:
    conn = op.get_bind()

    # Recreate old shape (one pattern per library). We keep the paper pattern when collapsing.
    op.create_table(
        'library_naming_patterns_old',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column('library_id', sa.String(length=36), sa.ForeignKey('libraries.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('pattern', sa.String(length=1024), nullable=False, server_default=''),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    try:
        rows = conn.execute(
            sa.text(
                "SELECT library_id, pattern, updated_at FROM library_naming_patterns WHERE file_type = 'paper'"
            )
        ).fetchall()
    except Exception:
        rows = []

    for (library_id, pattern, updated_at) in rows:
        conn.execute(
            sa.text(
                'INSERT INTO library_naming_patterns_old (library_id, pattern, updated_at) '
                'VALUES (:library_id, :pattern, :updated_at)'
            ),
            {
                'library_id': str(library_id),
                'pattern': str(pattern or ''),
                'updated_at': updated_at,
            },
        )

    op.drop_table('library_naming_patterns')
    op.rename_table('library_naming_patterns_old', 'library_naming_patterns')
