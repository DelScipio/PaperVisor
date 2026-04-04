"""markers_case_insensitive_unique

Revision ID: c4f9b2e7a1d3
Revises: f0795835d5ed
Create Date: 2026-03-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c4f9b2e7a1d3'
down_revision: Union[str, Sequence[str], None] = 'f0795835d5ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Merge existing case-insensitive duplicates per owner before adding unique index.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY LOWER(name), COALESCE(owner_user_id, -1)
                    ORDER BY created_at ASC, id ASC
                ) AS rn,
                FIRST_VALUE(id) OVER (
                    PARTITION BY LOWER(name), COALESCE(owner_user_id, -1)
                    ORDER BY created_at ASC, id ASC
                ) AS keep_id
            FROM markers
        ),
        dups AS (
            SELECT id AS dup_id, keep_id
            FROM ranked
            WHERE rn > 1
        )
        INSERT INTO paper_markers (paper_id, marker_id, created_at)
        SELECT pm.paper_id, d.keep_id, pm.created_at
        FROM paper_markers AS pm
        JOIN dups AS d ON d.dup_id = pm.marker_id
        LEFT JOIN paper_markers AS existing
            ON existing.paper_id = pm.paper_id
           AND existing.marker_id = d.keep_id
        WHERE existing.paper_id IS NULL
        """
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY LOWER(name), COALESCE(owner_user_id, -1)
                    ORDER BY created_at ASC, id ASC
                ) AS rn
            FROM markers
        )
        DELETE FROM paper_markers
        WHERE marker_id IN (
            SELECT id
            FROM ranked
            WHERE rn > 1
        )
        """
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY LOWER(name), COALESCE(owner_user_id, -1)
                    ORDER BY created_at ASC, id ASC
                ) AS rn
            FROM markers
        )
        DELETE FROM markers
        WHERE id IN (
            SELECT id
            FROM ranked
            WHERE rn > 1
        )
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_markers_owner_name_ci
        ON markers (LOWER(name), COALESCE(owner_user_id, -1))
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute('DROP INDEX IF EXISTS uq_markers_owner_name_ci')
