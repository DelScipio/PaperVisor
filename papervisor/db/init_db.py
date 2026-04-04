from __future__ import annotations

import logging
import os

from papervisor.core.config import get_paths

"""Database initialization.

On **first run** (empty database) we create all tables directly from
the SQLAlchemy model metadata and stamp the Alembic revision to the
current head so that future schema migrations are applied normally.

On **subsequent runs** we apply any pending Alembic migrations so the
schema is always up-to-date — this works both inside Docker and when
running locally via ``python main.py``.
"""

logger = logging.getLogger(__name__)

# Resolved once; shared by helpers.
_ALEMBIC_INI = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'alembic.ini',
)


def _allow_start_with_migration_errors() -> bool:
    val = str(os.environ.get('PAPERVISOR_ALLOW_START_WITH_MIGRATION_ERRORS', '0')).strip().lower()
    return val in {'1', 'true', 'yes', 'on'}


def _get_alembic_cfg():
    """Return an ``alembic.config.Config`` pointing at the project DB, or *None*."""
    from alembic.config import Config
    from papervisor.db.session import engine

    if not os.path.exists(_ALEMBIC_INI):
        logger.warning('alembic.ini not found at %s — skipping migration', _ALEMBIC_INI)
        return None

    cfg = Config(_ALEMBIC_INI)
    cfg.set_main_option('sqlalchemy.url', str(engine.url))
    return cfg


def _is_fresh_database() -> bool:
    """Return True when the database has no tables at all."""
    from papervisor.db.session import engine
    from sqlalchemy import inspect

    inspector = inspect(engine)
    return len(inspector.get_table_names()) == 0


def _has_alembic_version_table() -> bool:
    """Return True when Alembic bookkeeping table exists."""
    from papervisor.db.session import engine
    from sqlalchemy import inspect

    inspector = inspect(engine)
    return 'alembic_version' in set(inspector.get_table_names())


def _create_all_and_stamp() -> None:
    """Create every table from models and stamp Alembic to heads."""
    from papervisor.db.base import Base
    from papervisor.db import models as _models  # noqa: F401 — register tables
    from papervisor.db.session import engine
    from alembic import command

    logger.info('Fresh database detected — creating schema from models')
    Base.metadata.create_all(bind=engine)

    try:
        cfg = _get_alembic_cfg()
        if cfg is not None:
            command.stamp(cfg, 'heads')
            logger.info('Alembic stamped to heads')
    except Exception:
        logger.warning('Failed to stamp Alembic after schema creation', exc_info=True)


def _run_upgrades() -> None:
    """Apply any pending Alembic migrations on an existing database."""
    from alembic import command

    try:
        cfg = _get_alembic_cfg()
        if cfg is None:
            return

        logger.info('Applying pending Alembic migrations …')
        command.upgrade(cfg, 'head')
        logger.info('Alembic migrations applied')
    except Exception:
        if _allow_start_with_migration_errors():
            logger.warning(
                'Alembic upgrade failed — continuing because PAPERVISOR_ALLOW_START_WITH_MIGRATION_ERRORS is enabled',
                exc_info=True,
            )
            return
        logger.error('Alembic upgrade failed — refusing to start with unknown schema state', exc_info=True)
        raise


def init_db() -> None:
    paths = get_paths()
    paths.database_file.parent.mkdir(parents=True, exist_ok=True)
    paths.library_files_dir.mkdir(parents=True, exist_ok=True)

    if _is_fresh_database():
        _create_all_and_stamp()
        return

    # Recovery path for legacy/externally-created DBs that have tables but
    # were never stamped by Alembic. Running migrations from base in this
    # state can fail with "table already exists".
    if not _has_alembic_version_table():
        logger.warning(
            'Database has tables but no alembic_version table; '
            'bootstrapping schema/state with create_all + Alembic stamp'
        )
        _create_all_and_stamp()
        return

    _run_upgrades()
