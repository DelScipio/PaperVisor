from __future__ import annotations

import pytest

from papervisor.db import init_db as db_init


def test_allow_start_with_migration_errors_flag(monkeypatch) -> None:
    monkeypatch.delenv('PAPERVISOR_ALLOW_START_WITH_MIGRATION_ERRORS', raising=False)
    assert db_init._allow_start_with_migration_errors() is False

    monkeypatch.setenv('PAPERVISOR_ALLOW_START_WITH_MIGRATION_ERRORS', '1')
    assert db_init._allow_start_with_migration_errors() is True


def test_run_upgrades_raises_by_default_on_failure(monkeypatch) -> None:
    monkeypatch.delenv('PAPERVISOR_ALLOW_START_WITH_MIGRATION_ERRORS', raising=False)
    monkeypatch.setattr(db_init, '_get_alembic_cfg', lambda: object())

    def _raise_upgrade(*_args, **_kwargs):
        raise RuntimeError('upgrade boom')

    monkeypatch.setattr('alembic.command.upgrade', _raise_upgrade)

    with pytest.raises(RuntimeError, match='upgrade boom'):
        db_init._run_upgrades()


def test_run_upgrades_can_continue_when_override_enabled(monkeypatch) -> None:
    monkeypatch.setenv('PAPERVISOR_ALLOW_START_WITH_MIGRATION_ERRORS', '1')
    monkeypatch.setattr(db_init, '_get_alembic_cfg', lambda: object())

    def _raise_upgrade(*_args, **_kwargs):
        raise RuntimeError('upgrade boom')

    monkeypatch.setattr('alembic.command.upgrade', _raise_upgrade)

    # Should not raise when explicit fail-open flag is enabled.
    db_init._run_upgrades()
