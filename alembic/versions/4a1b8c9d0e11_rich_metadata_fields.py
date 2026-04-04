"""rich metadata fields

Revision ID: 4a1b8c9d0e11
Revises: 3d7a1c9e4f20
Create Date: 2026-01-06

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4a1b8c9d0e11'
down_revision: Union[str, Sequence[str], None] = '3d7a1c9e4f20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite-safe schema changes
    with op.batch_alter_table('papers', schema=None) as batch:
        # Book-specific
        batch.add_column(sa.Column('description', sa.String(length=8192), nullable=True))
        batch.add_column(sa.Column('language', sa.String(length=32), nullable=True))
        batch.add_column(sa.Column('genres', sa.String(length=1024), nullable=True))
        batch.add_column(sa.Column('publication_date', sa.String(length=32), nullable=True))
        batch.add_column(sa.Column('series', sa.String(length=256), nullable=True))
        batch.add_column(sa.Column('series_index', sa.String(length=32), nullable=True))
        batch.add_column(sa.Column('page_count', sa.Integer(), nullable=True))

        # Paper-specific
        batch.add_column(sa.Column('abstract', sa.String(length=8192), nullable=True))
        batch.add_column(sa.Column('url', sa.String(length=1024), nullable=True))
        batch.add_column(sa.Column('volume', sa.String(length=64), nullable=True))
        batch.add_column(sa.Column('issue', sa.String(length=64), nullable=True))
        batch.add_column(sa.Column('pages', sa.String(length=64), nullable=True))
        batch.add_column(sa.Column('keywords', sa.String(length=1024), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('papers', schema=None) as batch:
        batch.drop_column('keywords')
        batch.drop_column('pages')
        batch.drop_column('issue')
        batch.drop_column('volume')
        batch.drop_column('url')
        batch.drop_column('abstract')

        batch.drop_column('page_count')
        batch.drop_column('series_index')
        batch.drop_column('series')
        batch.drop_column('publication_date')
        batch.drop_column('genres')
        batch.drop_column('language')
        batch.drop_column('description')
