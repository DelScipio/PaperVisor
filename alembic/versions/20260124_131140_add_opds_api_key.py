"""add opds api key (deprecated)

This file accidentally got created as a new base head (down_revision=None),
duplicating the real OPDS API key migration.

It is kept to avoid breaking references to the revision id, but it is now
chained to the real history and does not apply any schema changes.

Revision ID: 9a325a988a02a49b
Revises: c1a2b3c4d5e6
Create Date: 2026-01-24T13:11:40.442632

"""

# NOTE: keep imports minimal; this migration is intentionally a no-op.


# revision identifiers, used by Alembic.
revision = '9a325a988a02a49b'
down_revision = 'c1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op; the real migration is 967e58fb1766.
    return


def downgrade() -> None:
    # No-op.
    return
