from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from papervisor.core.config import get_paths


_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar('papervisor_request_id', default=None)


def get_request_id() -> str | None:
    return _request_id_var.get()


def set_request_id(request_id: str | None) -> contextvars.Token[str | None]:
    return _request_id_var.set(request_id)


def reset_request_id(token: contextvars.Token[str | None]) -> None:
    _request_id_var.reset(token)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 (shadow built-in)
        setattr(record, 'request_id', get_request_id() or '-')
        return True


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, 'request_id'):
            setattr(record, 'request_id', '-')
        return super().format(record)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            'ts': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'msg': record.getMessage(),
            'request_id': getattr(record, 'request_id', '-') or '-',
        }
        if record.exc_info:
            payload['exc_info'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_int(name: str, default: int, *, min_value: int) -> int:
    raw = str(os.environ.get(name, str(default))).strip()
    try:
        value = int(raw)
    except ValueError:
        logging.getLogger(__name__).warning(
            'Invalid %s value %r; using default %d',
            name,
            raw,
            default,
        )
        return default
    if value < min_value:
        logging.getLogger(__name__).warning(
            'Invalid %s value %r; using minimum %d',
            name,
            value,
            min_value,
        )
        return min_value
    return value


def setup_logging() -> None:
    """Configure app logging.

    Env vars:
    - PAPERVISOR_LOG_LEVEL: DEBUG/INFO/WARNING/ERROR (default INFO)
    - PAPERVISOR_LOG_JSON: 1 for JSON logs (default 0)
    - PAPERVISOR_LOG_FILE: override log file path
    - PAPERVISOR_LOG_MAX_BYTES: rotate size (default 5MB)
    - PAPERVISOR_LOG_BACKUP_COUNT: rotated files kept (default 5)
    """

    level_name = str(os.environ.get('PAPERVISOR_LOG_LEVEL', 'INFO')).strip().upper() or 'INFO'
    level = getattr(logging, level_name, logging.INFO)

    json_logs = _env_bool('PAPERVISOR_LOG_JSON', default=False)

    # Ensure we don't double-configure under reload.
    root = logging.getLogger()
    root.setLevel(level)

    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            logging.getLogger(__name__).debug('Failed to close old log handler', exc_info=True)

    fmt_text = '%(asctime)s %(levelname)s [%(name)s] [rid=%(request_id)s] %(message)s'

    formatter: logging.Formatter
    if json_logs:
        formatter = _JsonFormatter()
    else:
        formatter = _TextFormatter(fmt_text)

    request_id_filter = _RequestIdFilter()

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(formatter)
    console.addFilter(request_id_filter)
    root.addHandler(console)

    # File logging (rotating)
    try:
        paths = get_paths()
        default_log_file = paths.project_root / 'logs' / 'papervisor.log'
        log_file = Path(os.environ.get('PAPERVISOR_LOG_FILE') or default_log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        max_bytes = _env_int('PAPERVISOR_LOG_MAX_BYTES', 5 * 1024 * 1024, min_value=1)
        backup_count = _env_int('PAPERVISOR_LOG_BACKUP_COUNT', 5, min_value=0)

        file_handler = RotatingFileHandler(
            filename=str(log_file),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8',
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(request_id_filter)
        root.addHandler(file_handler)
    except Exception:
        # Best-effort: console logging still works.
        logging.getLogger(__name__).exception('Failed to configure file logging handler')

    # Quiet noisy loggers a bit (override via level if needed).
    logging.getLogger('uvicorn').setLevel(max(level, logging.INFO))
    logging.getLogger('uvicorn.error').setLevel(max(level, logging.INFO))
    logging.getLogger('uvicorn.access').setLevel(max(level, logging.INFO))


def new_request_id() -> str:
    return uuid.uuid4().hex
