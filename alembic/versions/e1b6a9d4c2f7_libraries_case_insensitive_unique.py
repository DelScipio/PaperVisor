"""libraries_case_insensitive_unique

Revision ID: e1b6a9d4c2f7
Revises: c4f9b2e7a1d3
Create Date: 2026-03-15 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e1b6a9d4c2f7'
down_revision: Union[str, Sequence[str], None] = 'c4f9b2e7a1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Merge existing case-insensitive duplicate libraries by keeping the oldest one.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY LOWER(name)
                    ORDER BY created_at ASC, id ASC
                ) AS rn,
                FIRST_VALUE(id) OVER (
                    PARTITION BY LOWER(name)
                    ORDER BY created_at ASC, id ASC
                ) AS keep_id
            FROM libraries
        ),
        dups AS (
            SELECT id AS dup_id, keep_id
            FROM ranked
            WHERE rn > 1
        )
        UPDATE papers
        SET library_id = (
            SELECT d.keep_id
            FROM dups AS d
            WHERE d.dup_id = papers.library_id
        )
        WHERE library_id IN (SELECT dup_id FROM dups)
        """
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY LOWER(name)
                    ORDER BY created_at ASC, id ASC
                ) AS rn,
                FIRST_VALUE(id) OVER (
                    PARTITION BY LOWER(name)
                    ORDER BY created_at ASC, id ASC
                ) AS keep_id
            FROM libraries
        ),
        dups AS (
            SELECT id AS dup_id, keep_id
            FROM ranked
            WHERE rn > 1
        )
        INSERT INTO hidden_global_libraries (user_id, library_id, created_at)
        SELECT h.user_id, d.keep_id, h.created_at
        FROM hidden_global_libraries AS h
        JOIN dups AS d ON d.dup_id = h.library_id
        LEFT JOIN hidden_global_libraries AS existing
            ON existing.user_id = h.user_id
           AND existing.library_id = d.keep_id
        WHERE existing.user_id IS NULL
        """
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY LOWER(name)
                    ORDER BY created_at ASC, id ASC
                ) AS rn,
                FIRST_VALUE(id) OVER (
                    PARTITION BY LOWER(name)
                    ORDER BY created_at ASC, id ASC
                ) AS keep_id
            FROM libraries
        ),
        dups AS (
            SELECT id AS dup_id, keep_id
            FROM ranked
            WHERE rn > 1
        )
        INSERT INTO library_naming_patterns (library_id, file_type, pattern, updated_at)
        SELECT lnp.library_id, lnp.file_type, lnp.pattern, lnp.updated_at
        FROM (
            SELECT d.keep_id AS library_id, p.file_type, p.pattern, p.updated_at
            FROM library_naming_patterns AS p
            JOIN dups AS d ON d.dup_id = p.library_id
        ) AS lnp
        LEFT JOIN library_naming_patterns AS existing
            ON existing.library_id = lnp.library_id
           AND existing.file_type = lnp.file_type
        WHERE existing.id IS NULL
        """
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY LOWER(name)
                    ORDER BY created_at ASC, id ASC
                ) AS rn
            FROM libraries
        )
        DELETE FROM hidden_global_libraries
        WHERE library_id IN (
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
                    PARTITION BY LOWER(name)
                    ORDER BY created_at ASC, id ASC
                ) AS rn
            FROM libraries
        )
        DELETE FROM library_naming_patterns
        WHERE library_id IN (
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
                    PARTITION BY LOWER(name)
                    ORDER BY created_at ASC, id ASC
                ) AS rn
            FROM libraries
        )
        DELETE FROM library_shares
        WHERE library_id IN (
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
                    PARTITION BY LOWER(name)
                    ORDER BY created_at ASC, id ASC
                ) AS rn
            FROM libraries
        )
        DELETE FROM libraries
        WHERE id IN (
            SELECT id
            FROM ranked
            WHERE rn > 1
        )
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_libraries_name_ci
        ON libraries (LOWER(name))
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute('DROP INDEX IF EXISTS uq_libraries_name_ci')
