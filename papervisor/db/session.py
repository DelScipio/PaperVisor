from __future__ import annotations

import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from papervisor.core.config import get_paths


def _parse_int_env(name: str, default: int, *, min_value: int, max_value: int) -> int:
    raw = str(os.environ.get(name, str(default)) or str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_value, min(max_value, value))


def _database_url() -> str:
    env_url = os.environ.get('PAPERVISOR_DATABASE_URL') or os.environ.get('DATABASE_URL')
    if env_url:
        return env_url
    paths = get_paths()
    # Using a file-based SQLite DB in the project root keeps things simple for now.
    return f"sqlite:///{paths.database_file.as_posix()}"


engine = create_engine(
    _database_url(),
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, 'connect')
def _set_sqlite_pragma(dbapi_connection: sqlite3.Connection, _connection_record: object) -> None:
    # SQLite does NOT enforce foreign keys unless explicitly enabled.
    # Without this, deletions (e.g., users) can leave orphan rows.
    try:
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')

            # Performance/concurrency tuning (safe defaults; override via env).
            # Notes:
            # - WAL greatly improves concurrency for read-heavy workloads.
            # - Some network filesystems can behave poorly with WAL; disable with PAPERVISOR_SQLITE_WAL=0.
            wal_env = str(os.environ.get('PAPERVISOR_SQLITE_WAL', '1')).strip().lower()
            wal_on = wal_env not in {'0', 'false', 'no', 'off'}
            if wal_on:
                try:
                    cursor.execute('PRAGMA journal_mode=WAL')
                    cursor.execute('PRAGMA synchronous=NORMAL')
                except sqlite3.Error:
                    pass

            # Wait a bit on write locks instead of failing fast.
            try:
                timeout_ms = _parse_int_env(
                    'PAPERVISOR_SQLITE_BUSY_TIMEOUT_MS',
                    5000,
                    min_value=0,
                    max_value=60000,
                )
                cursor.execute(f'PRAGMA busy_timeout={timeout_ms}')
            except sqlite3.Error:
                pass

            # Keep some working set in memory.
            # Negative cache_size is KiB; -20000 ~ 20 MiB.
            try:
                cache_kib = _parse_int_env(
                    'PAPERVISOR_SQLITE_CACHE_KIB',
                    -20000,
                    min_value=-262144,
                    max_value=262144,
                )
                if cache_kib == 0:
                    cache_kib = -20000
                cursor.execute(f'PRAGMA cache_size={cache_kib}')
            except sqlite3.Error:
                pass

            # Prefer in-memory temp storage for sort/joins.
            try:
                cursor.execute('PRAGMA temp_store=MEMORY')
            except sqlite3.Error:
                pass

            cursor.close()
    except (sqlite3.Error, AttributeError, TypeError):
        # Best-effort: don't block app startup.
        pass

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_session() -> Session:
    """Create a new standalone session.

    Callers are responsible for calling ``session.commit()`` /
    ``session.close()``, typically via a ``with`` block::

        with get_session() as session:
            ...
            session.commit()

    For FastAPI dependency injection, prefer :func:`get_db` instead.
    """
    return SessionLocal()


def get_db() -> Generator[Session, None, None]:
    """FastAPI-compatible dependency that yields a request-scoped session.

    Usage in API endpoints::

        @app.get('/something')
        def handler(db: Session = Depends(get_db)):
            ...

    The session is automatically closed after the request.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def use_session(session: Session | None = None) -> Generator[Session, None, None]:
    """Context manager that reuses *session* if given, else creates a new one.

    When a new session is created, it is closed on exit.  An externally
    supplied session is **not** closed (the caller owns its lifecycle).

    This is the recommended pattern for service functions that want to
    participate in an outer transaction when one is provided, but still
    work standalone::

        def my_service_fn(*, session: Session | None = None) -> ...:
            with use_session(session) as s:
                ...
                s.commit()   # safe: commits new session or outer txn
    """
    if session is not None:
        yield session
    else:
        new_session = SessionLocal()
        try:
            yield new_session
        finally:
            new_session.close()
