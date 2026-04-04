"""paper metadata and library link

Revision ID: 86b2d2a9b1f0
Revises: 6d4a7c6f8c2a
Create Date: 2026-01-04

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '86b2d2a9b1f0'
down_revision = '6d4a7c6f8c2a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('papers', recreate='always') as batch:
        batch.add_column(sa.Column('library_id', sa.String(length=36), nullable=True))
        batch.add_column(sa.Column('file_type', sa.String(length=16), nullable=False, server_default='paper'))
        batch.add_column(sa.Column('doi', sa.String(length=255), nullable=True))
        batch.add_column(sa.Column('authors', sa.String(length=2048), nullable=True))
        batch.add_column(sa.Column('published_year', sa.String(length=16), nullable=True))
        batch.add_column(sa.Column('journal', sa.String(length=512), nullable=True))
        batch.add_column(sa.Column('publisher', sa.String(length=512), nullable=True))
        batch.add_column(sa.Column('isbn', sa.String(length=64), nullable=True))
        batch.create_foreign_key('fk_papers_library_id', 'libraries', ['library_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('papers', recreate='always') as batch:
        batch.drop_constraint('fk_papers_library_id', type_='foreignkey')
        batch.drop_column('isbn')
        batch.drop_column('publisher')
        batch.drop_column('journal')
        batch.drop_column('published_year')
        batch.drop_column('authors')
        batch.drop_column('doi')
        batch.drop_column('file_type')
        batch.drop_column('library_id')
