from __future__ import annotations

"""Application configuration with validation.

``AppSettings`` consolidates all environment-variable driven settings
into a single validated object.  It is read once at import time, cached
in ``_settings``, and accessed via ``get_settings()``.

``Paths`` remains a lightweight frozen dataclass for backward
compatibility with callers that only need filesystem paths.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ---- Paths (legacy helper) -------------------------------------------

@dataclass(frozen=True)
class Paths:
    project_root: Path
    database_file: Path
    library_files_dir: Path


def get_paths() -> Paths:
    s = get_settings()
    return Paths(
        project_root=s.project_root,
        database_file=s.database_file,
        library_files_dir=s.library_files_dir,
    )


# ---- Application settings --------------------------------------------

@dataclass
class AppSettings:
    """Validated application configuration sourced from environment variables.

    All values receive sensible defaults.  Invalid values are logged as
    warnings and fall back to defaults — the application never crashes
    because of a mis-typed env var.
    """

    # Core paths
    project_root: Path
    database_file: Path
    library_files_dir: Path

    # Networking
    host: str | None
    port: int | None
    reload: bool

    # Security
    storage_secret: str | None
    require_storage_secret: bool
    trusted_proxies: str | None

    # Feature flags / tunables
    debug_render: bool


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def _parse_int(raw: str | None, *, default: int | None = None, name: str = '') -> int | None:
    if not raw:
        return default
    raw = raw.strip()
    try:
        return int(raw)
    except ValueError:
        logger.warning('Invalid integer for %s: %r — using default %s', name, raw, default)
        return default


def _parse_port(raw: str | None, *, default: int | None = None, name: str = 'PAPERVISOR_PORT') -> int | None:
    port = _parse_int(raw, default=default, name=name)
    if port is None:
        return default
    if 1 <= port <= 65535:
        return port
    logger.warning('Invalid port for %s: %r — using default %s', name, port, default)
    return default


def _parse_path(raw: str | None, *, default: Path, base_dir: Path, name: str = '') -> Path:
    if not raw:
        return default
    try:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = base_dir / p
        return p.resolve()
    except (OSError, RuntimeError, ValueError):
        logger.warning('Invalid path for %s: %r — using default %s', name, raw, default)
        return default


def _load_settings() -> AppSettings:
    """Read environment variables and build a validated ``AppSettings``."""
    project_root = Path(__file__).resolve().parents[2]

    database_file = _parse_path(
        os.environ.get('PAPERVISOR_DB_PATH'),
        default=(project_root / 'papervisor.db').resolve(),
        base_dir=project_root,
        name='PAPERVISOR_DB_PATH',
    )

    library_files_dir = _parse_path(
        os.environ.get('PAPERVISOR_LIBRARY_DIR'),
        default=(project_root / 'library_files').resolve(),
        base_dir=project_root,
        name='PAPERVISOR_LIBRARY_DIR',
    )

    host = os.environ.get('PAPERVISOR_HOST') or None
    port_raw = os.environ.get('PAPERVISOR_PORT')
    if port_raw is not None:
        port = _parse_port(port_raw, name='PAPERVISOR_PORT')
        if port is None:
            port = _parse_port(os.environ.get('PORT'), name='PORT')
    else:
        port = _parse_port(os.environ.get('PORT'), name='PORT')

    # Reload defaults to True for dev ergonomics; Docker sets to 0.
    reload_raw = os.environ.get('PAPERVISOR_RELOAD')
    if reload_raw is None:
        reload = True
    else:
        reload = _parse_bool(reload_raw, default=False)

    storage_secret = (
        os.environ.get('PAPERVISOR_STORAGE_SECRET')
        or os.environ.get('NICEGUI_STORAGE_SECRET')
        or None
    )

    require_storage_secret = _parse_bool(
        os.environ.get('PAPERVISOR_REQUIRE_STORAGE_SECRET'),
        default=False,
    )

    trusted_proxies = os.environ.get('PAPERVISOR_TRUSTED_PROXIES') or None

    debug_render = _parse_bool(
        os.environ.get('PAPERVISOR_DEBUG_RENDER'),
        default=False,
    )

    settings = AppSettings(
        project_root=project_root,
        database_file=database_file,
        library_files_dir=library_files_dir,
        host=host,
        port=port,
        reload=reload,
        storage_secret=storage_secret,
        require_storage_secret=require_storage_secret,
        trusted_proxies=trusted_proxies,
        debug_render=debug_render,
    )

    # Log a summary of resolved configuration at startup.
    _log_summary(settings)
    return settings


def _log_summary(s: AppSettings) -> None:
    """Emit a concise startup summary at DEBUG level."""
    logger.debug('Configuration:')
    logger.debug('  database   = %s', s.database_file)
    logger.debug('  library    = %s', s.library_files_dir)
    logger.debug('  host:port  = %s:%s', s.host or '(default)', s.port or '(default)')
    logger.debug('  reload     = %s', s.reload)
    logger.debug('  secret set = %s', bool(s.storage_secret))
    logger.debug('  require storage secret = %s', s.require_storage_secret)


# ---- Singleton accessor -----------------------------------------------

_settings: AppSettings | None = None


def get_settings() -> AppSettings:
    """Return the cached ``AppSettings`` instance (created on first call)."""
    global _settings
    if _settings is None:
        _settings = _load_settings()
    return _settings
