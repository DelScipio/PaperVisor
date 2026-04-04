"""migrate/remove global favorites

Revision ID: 3d7a1c9e4f20
Revises: 2a6d4c7e9b11
Create Date: 2026-01-06

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d7a1c9e4f20'
down_revision: Union[str, Sequence[str], None] = '2a6d4c7e9b11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1) Backfill: assign any legacy global favorites to user 'pmmsoares'.
    try:
        uid = conn.execute(
            sa.text('SELECT id FROM users WHERE username = :u ORDER BY id ASC LIMIT 1'),
            {'u': 'pmmsoares'},
        ).scalar()
    except Exception:
        uid = None

    if uid is None:
        try:
            uid = conn.execute(sa.text('SELECT id FROM users ORDER BY id ASC LIMIT 1')).scalar()
        except Exception:
            uid = None

    if uid is not None:
        try:
            paper_ids = [
                str(r[0])
                for r in conn.execute(sa.text('SELECT id FROM papers WHERE is_favorite = 1')).fetchall()
            ]
            for pid in paper_ids:
                conn.execute(
                    sa.text('INSERT OR IGNORE INTO paper_favorites (user_id, paper_id) VALUES (:uid, :pid)'),
                    {'uid': int(uid), 'pid': pid},
                )
        except Exception:
            # If the column doesn't exist (unexpected) or anything else fails, proceed to drop.
            pass

    # 2) Drop legacy global flag column.
    with op.batch_alter_table('papers', schema=None) as batch:
        batch.drop_column('is_favorite')


def downgrade() -> None:
    # Restore the legacy column (data is not reconstructed).
    with op.batch_alter_table('papers', schema=None) as batch:
        batch.add_column(sa.Column('is_favorite', sa.Boolean(), nullable=False, server_default=sa.false()))
