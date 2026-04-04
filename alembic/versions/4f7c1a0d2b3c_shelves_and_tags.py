"""shelves and tags

Revision ID: 4f7c1a0d2b3c
Revises: 32a4dc706adf
Create Date: 2026-01-05

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f7c1a0d2b3c'
down_revision: Union[str, Sequence[str], None] = '32a4dc706adf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'shelves' not in existing_tables:
        op.create_table(
            'shelves',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('name', sa.String(length=128), nullable=False),
            sa.Column('icon', sa.String(length=64), nullable=False, server_default='category'),
            sa.Column('is_smart', sa.Boolean(), nullable=False, server_default=sa.text('0')),
            sa.Column('scope', sa.String(length=16), nullable=False, server_default='all'),
            sa.Column('rules_json', sa.String(length=8192), nullable=False, server_default=''),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint('name', name='uq_shelves_name'),
        )

    if 'paper_shelves' not in existing_tables:
        op.create_table(
            'paper_shelves',
            sa.Column('paper_id', sa.String(length=64), nullable=False),
            sa.Column('shelf_id', sa.String(length=36), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('paper_id', 'shelf_id', name='pk_paper_shelves'),
            sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['shelf_id'], ['shelves.id'], ondelete='CASCADE'),
        )

    if 'tags' not in existing_tables:
        op.create_table(
            'tags',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('name', sa.String(length=64), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint('name', name='uq_tags_name'),
        )

    if 'paper_tags' not in existing_tables:
        op.create_table(
            'paper_tags',
            sa.Column('paper_id', sa.String(length=64), nullable=False),
            sa.Column('tag_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('paper_id', 'tag_id', name='pk_paper_tags'),
            sa.ForeignKeyConstraint(['paper_id'], ['papers.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
        )


def downgrade() -> None:
    op.drop_table('paper_tags')
    op.drop_table('tags')
    op.drop_table('paper_shelves')
    op.drop_table('shelves')
