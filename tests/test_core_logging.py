from __future__ import annotations

import logging
from types import SimpleNamespace

from papervisor.core import logging as pv_logging


def test_setup_logging_invalid_numeric_env_falls_back(monkeypatch, capsys) -> None:
    monkeypatch.setenv('PAPERVISOR_LOG_MAX_BYTES', 'not-an-int')
    monkeypatch.setenv('PAPERVISOR_LOG_BACKUP_COUNT', '-4')
    monkeypatch.setattr(
        pv_logging,
        'get_paths',
        lambda: SimpleNamespace(project_root=pv_logging.Path('/tmp/papervisor-test')),
    )

    pv_logging.setup_logging()
    messages = capsys.readouterr().err
    assert 'Invalid PAPERVISOR_LOG_MAX_BYTES' in messages
    assert 'Invalid PAPERVISOR_LOG_BACKUP_COUNT' in messages


def test_setup_logging_logs_file_handler_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        pv_logging,
        'get_paths',
        lambda: SimpleNamespace(project_root=pv_logging.Path('/tmp/papervisor-test')),
    )

    def _raise(*args, **kwargs):
        raise OSError('disk full')

    monkeypatch.setattr(pv_logging, 'RotatingFileHandler', _raise)

    pv_logging.setup_logging()
    messages = capsys.readouterr().err
    assert 'Failed to configure file logging handler' in messages

    # Console logging should still be configured.
    root_handlers = logging.getLogger().handlers
    assert root_handlers


def test_setup_logging_closes_existing_handlers(monkeypatch) -> None:
    monkeypatch.setattr(
        pv_logging,
        'get_paths',
        lambda: SimpleNamespace(project_root=pv_logging.Path('/tmp/papervisor-test')),
    )

    class _CloseTrackingHandler(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.closed_called = False

        def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - not used in test
            return None

        def close(self) -> None:
            self.closed_called = True
            super().close()

    old_handler = _CloseTrackingHandler()
    root = logging.getLogger()
    root.handlers = [old_handler]

    pv_logging.setup_logging()

    assert old_handler not in root.handlers
    assert old_handler.closed_called is True
