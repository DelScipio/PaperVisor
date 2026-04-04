"""user favorites

Revision ID: 1f3a8b9c2d10
Revises: 0b2c4d8a1e7f
Create Date: 2026-01-06

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1f3a8b9c2d10'
down_revision: Union[str, Sequence[str], None] = '0b2c4d8a1e7f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'paper_favorites',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True, nullable=False),
        sa.Column('paper_id', sa.String(length=64), sa.ForeignKey('papers.id', ondelete='CASCADE'), primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('(CURRENT_TIMESTAMP)')),
    )
    op.create_index('ix_paper_favorites_user_id', 'paper_favorites', ['user_id'])
    op.create_index('ix_paper_favorites_paper_id', 'paper_favorites', ['paper_id'])

    # Best-effort migration of the old global flag:
    # - If there is exactly ONE user, treat existing global favorites as belonging to that user.
    # - If there are multiple users, we cannot know who favorited what, so we leave favorites empty.
    bind = op.get_bind()
    try:
        user_ids = [int(r[0]) for r in bind.execute(sa.text('SELECT id FROM users ORDER BY id ASC')).fetchall()]
        if len(user_ids) == 1:
            uid = int(user_ids[0])
            fav_paper_ids = [
                str(r[0])
                for r in bind.execute(sa.text("SELECT id FROM papers WHERE is_favorite = 1")).fetchall()
            ]
            for pid in fav_paper_ids:
                bind.execute(
                    sa.text(
                        'INSERT OR IGNORE INTO paper_favorites (user_id, paper_id) VALUES (:uid, :pid)'
                    ),
                    {'uid': uid, 'pid': pid},
                )
    except Exception:
        # Keep migration resilient; favorites can be re-set by users.
        pass


def downgrade() -> None:
    op.drop_index('ix_paper_favorites_paper_id', table_name='paper_favorites')
    op.drop_index('ix_paper_favorites_user_id', table_name='paper_favorites')
    op.drop_table('paper_favorites')
