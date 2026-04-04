"""library and file sharing

Revision ID: c2a9f6a1d0b4
Revises: b1c3e2a4f5d6
Create Date: 2026-01-05

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c2a9f6a1d0b4'
down_revision = 'b1c3e2a4f5d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Libraries: owner + scope
    with op.batch_alter_table('libraries') as batch:
        batch.add_column(sa.Column('owner_user_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('scope', sa.String(length=16), nullable=False, server_default='private'))
        batch.create_foreign_key('fk_libraries_owner_user_id_users', 'users', ['owner_user_id'], ['id'], ondelete='SET NULL')

    # Best-effort backfill: assign existing libraries to the first admin user, else first user.
    conn = op.get_bind()
    try:
        admin_id = conn.execute(sa.text('SELECT id FROM users WHERE is_admin = 1 ORDER BY id ASC LIMIT 1')).scalar()
    except Exception:
        admin_id = None

    try:
        first_id = conn.execute(sa.text('SELECT id FROM users ORDER BY id ASC LIMIT 1')).scalar()
    except Exception:
        first_id = None

    owner_id = admin_id or first_id
    if owner_id is not None:
        try:
            conn.execute(sa.text('UPDATE libraries SET owner_user_id = :uid WHERE owner_user_id IS NULL'), {'uid': int(owner_id)})
        except Exception:
            pass

    # library_shares
    op.create_table(
        'library_shares',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('library_id', sa.String(length=36), sa.ForeignKey('libraries.id', ondelete='CASCADE'), nullable=False),
        sa.Column('shared_with_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('shared_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('role', sa.String(length=16), nullable=False, server_default='reader'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('library_id', 'shared_with_user_id', name='uq_library_shares_library_user'),
    )
    op.create_index('ix_library_shares_with_user_status', 'library_shares', ['shared_with_user_id', 'status'])

    # paper_shares
    op.create_table(
        'paper_shares',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('paper_id', sa.String(length=64), sa.ForeignKey('papers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('shared_with_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('shared_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('paper_id', 'shared_with_user_id', name='uq_paper_shares_paper_user'),
    )
    op.create_index('ix_paper_shares_with_user_status', 'paper_shares', ['shared_with_user_id', 'status'])


def downgrade() -> None:
    op.drop_index('ix_paper_shares_with_user_status', table_name='paper_shares')
    op.drop_table('paper_shares')

    op.drop_index('ix_library_shares_with_user_status', table_name='library_shares')
    op.drop_table('library_shares')

    with op.batch_alter_table('libraries') as batch:
        try:
            batch.drop_constraint('fk_libraries_owner_user_id_users', type_='foreignkey')
        except Exception:
            pass
        try:
            batch.drop_column('scope')
        except Exception:
            pass
        try:
            batch.drop_column('owner_user_id')
        except Exception:
            pass
