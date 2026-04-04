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
    monkeypatch.setattr(db_init, '_has_alembic_version_table', lambda: True)
    monkeypatch.setattr(db_init, '_alembic_version_has_rows', lambda: True)
    monkeypatch.setattr(db_init, '_has_user_tables_excluding_alembic_version', lambda: True)

    def _raise_upgrade(*_args, **_kwargs):
        raise RuntimeError('upgrade boom')

    monkeypatch.setattr('alembic.command.upgrade', _raise_upgrade)

    with pytest.raises(RuntimeError, match='upgrade boom'):
        db_init._run_upgrades()


def test_run_upgrades_can_continue_when_override_enabled(monkeypatch) -> None:
    monkeypatch.setenv('PAPERVISOR_ALLOW_START_WITH_MIGRATION_ERRORS', '1')
    monkeypatch.setattr(db_init, '_get_alembic_cfg', lambda: object())
    monkeypatch.setattr(db_init, '_has_alembic_version_table', lambda: True)
    monkeypatch.setattr(db_init, '_alembic_version_has_rows', lambda: True)
    monkeypatch.setattr(db_init, '_has_user_tables_excluding_alembic_version', lambda: True)

    def _raise_upgrade(*_args, **_kwargs):
        raise RuntimeError('upgrade boom')

    monkeypatch.setattr('alembic.command.upgrade', _raise_upgrade)

    # Should not raise when explicit fail-open flag is enabled.
    db_init._run_upgrades()


def test_run_upgrades_stamps_heads_when_version_table_is_empty_but_schema_exists(monkeypatch) -> None:
    monkeypatch.delenv('PAPERVISOR_ALLOW_START_WITH_MIGRATION_ERRORS', raising=False)
    monkeypatch.setattr(db_init, '_get_alembic_cfg', lambda: object())
    monkeypatch.setattr(db_init, '_has_alembic_version_table', lambda: True)
    monkeypatch.setattr(db_init, '_alembic_version_has_rows', lambda: False)
    monkeypatch.setattr(db_init, '_has_user_tables_excluding_alembic_version', lambda: True)

    called = {'stamp': 0, 'upgrade': 0}

    def _stamp(*_args, **_kwargs):
        called['stamp'] += 1

    def _upgrade(*_args, **_kwargs):
        called['upgrade'] += 1

    monkeypatch.setattr('alembic.command.stamp', _stamp)
    monkeypatch.setattr('alembic.command.upgrade', _upgrade)

    db_init._run_upgrades()

    assert called['stamp'] == 1
    assert called['upgrade'] == 0


def test_run_upgrades_runs_normal_upgrade_when_version_table_empty_and_schema_empty(monkeypatch) -> None:
    monkeypatch.delenv('PAPERVISOR_ALLOW_START_WITH_MIGRATION_ERRORS', raising=False)
    monkeypatch.setattr(db_init, '_get_alembic_cfg', lambda: object())
    monkeypatch.setattr(db_init, '_has_alembic_version_table', lambda: True)
    monkeypatch.setattr(db_init, '_alembic_version_has_rows', lambda: False)
    monkeypatch.setattr(db_init, '_has_user_tables_excluding_alembic_version', lambda: False)

    called = {'stamp': 0, 'upgrade': 0}

    def _stamp(*_args, **_kwargs):
        called['stamp'] += 1

    def _upgrade(*_args, **_kwargs):
        called['upgrade'] += 1

    monkeypatch.setattr('alembic.command.stamp', _stamp)
    monkeypatch.setattr('alembic.command.upgrade', _upgrade)

    db_init._run_upgrades()

    assert called['stamp'] == 0
    assert called['upgrade'] == 1


def test_should_bootstrap_schema_for_fresh_db(monkeypatch) -> None:
    monkeypatch.setattr(db_init, '_is_fresh_database', lambda: True)
    monkeypatch.setattr(db_init, '_has_alembic_version_table', lambda: True)

    assert db_init._should_bootstrap_schema() is True


def test_should_bootstrap_schema_for_unversioned_existing_db(monkeypatch) -> None:
    monkeypatch.setattr(db_init, '_is_fresh_database', lambda: False)
    monkeypatch.setattr(db_init, '_has_alembic_version_table', lambda: False)

    assert db_init._should_bootstrap_schema() is True


def test_should_not_bootstrap_when_versioned_existing_db(monkeypatch) -> None:
    monkeypatch.setattr(db_init, '_is_fresh_database', lambda: False)
    monkeypatch.setattr(db_init, '_has_alembic_version_table', lambda: True)

    assert db_init._should_bootstrap_schema() is False


def test_init_db_bootstraps_when_tables_exist_without_alembic_version(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        db_init,
        'get_paths',
        lambda: type('P', (), {'database_file': tmp_path / 'papervisor.db', 'library_files_dir': tmp_path / 'files'})(),
    )
    monkeypatch.setattr(db_init, '_should_bootstrap_schema', lambda: True)

    called = {'create': 0, 'upgrade': 0}

    monkeypatch.setattr(db_init, '_create_all_and_stamp', lambda: called.__setitem__('create', called['create'] + 1))
    monkeypatch.setattr(db_init, '_run_upgrades', lambda: called.__setitem__('upgrade', called['upgrade'] + 1))

    db_init.init_db()

    assert called['create'] == 1
    assert called['upgrade'] == 0


def test_init_db_runs_upgrades_when_alembic_version_exists(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        db_init,
        'get_paths',
        lambda: type('P', (), {'database_file': tmp_path / 'papervisor.db', 'library_files_dir': tmp_path / 'files'})(),
    )
    monkeypatch.setattr(db_init, '_should_bootstrap_schema', lambda: False)

    called = {'create': 0, 'upgrade': 0}

    monkeypatch.setattr(db_init, '_create_all_and_stamp', lambda: called.__setitem__('create', called['create'] + 1))
    monkeypatch.setattr(db_init, '_run_upgrades', lambda: called.__setitem__('upgrade', called['upgrade'] + 1))

    db_init.init_db()

    assert called['create'] == 0
    assert called['upgrade'] == 1
