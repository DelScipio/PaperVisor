"""add audit log events table

Revision ID: d3e4f5a6b7c8
Revises: b2c3d4e5f6a7
Create Date: 2026-02-17

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd3e4f5a6b7c8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def _create_index_if_missing(name: str, table: str, cols: list[str]) -> None:
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
    op.create_table(
        'audit_log_events',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('level', sa.String(length=16), nullable=False, server_default='info'),
        sa.Column('category', sa.String(length=32), nullable=False, server_default='auth'),
        sa.Column('action', sa.String(length=64), nullable=False, server_default='event'),
        sa.Column('message', sa.String(length=1024), nullable=False, server_default=''),
        sa.Column('details_json', sa.String(length=4096), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('username', sa.String(length=64), nullable=True),
        sa.Column('ip_address', sa.String(length=64), nullable=True),
        sa.Column('request_id', sa.String(length=64), nullable=True),
    )

    _create_index_if_missing('ix_audit_log_events_created_at', 'audit_log_events', ['created_at'])
    _create_index_if_missing('ix_audit_log_events_category_created_at', 'audit_log_events', ['category', 'created_at'])
    _create_index_if_missing('ix_audit_log_events_level_created_at', 'audit_log_events', ['level', 'created_at'])


def downgrade() -> None:
    for name in [
        'ix_audit_log_events_level_created_at',
        'ix_audit_log_events_category_created_at',
        'ix_audit_log_events_created_at',
    ]:
        try:
            op.drop_index(name)
        except Exception:
            pass

    op.drop_table('audit_log_events')
