from __future__ import annotations

from pathlib import Path

from papervisor.core import config


def _load_with_env(monkeypatch, *, port: str | None = None, db_path: str | None = None, library_path: str | None = None) -> config.AppSettings:
    monkeypatch.delenv('PAPERVISOR_PORT', raising=False)
    monkeypatch.delenv('PORT', raising=False)
    monkeypatch.delenv('PAPERVISOR_DB_PATH', raising=False)
    monkeypatch.delenv('PAPERVISOR_LIBRARY_DIR', raising=False)

    if port is not None:
        monkeypatch.setenv('PAPERVISOR_PORT', port)
    if db_path is not None:
        monkeypatch.setenv('PAPERVISOR_DB_PATH', db_path)
    if library_path is not None:
        monkeypatch.setenv('PAPERVISOR_LIBRARY_DIR', library_path)

    config._settings = None
    return config.get_settings()


def test_port_out_of_range_falls_back_to_default(monkeypatch) -> None:
    settings = _load_with_env(monkeypatch, port='70000')
    assert settings.port is None

    settings2 = _load_with_env(monkeypatch, port='-1')
    assert settings2.port is None


def test_relative_paths_resolve_under_project_root(monkeypatch) -> None:
    settings = _load_with_env(
        monkeypatch,
        db_path='var/data/pv.sqlite3',
        library_path='data/library_files',
    )

    assert settings.database_file.is_absolute()
    assert settings.library_files_dir.is_absolute()
    assert settings.database_file == (settings.project_root / Path('var/data/pv.sqlite3')).resolve()
    assert settings.library_files_dir == (settings.project_root / Path('data/library_files')).resolve()


def test_invalid_primary_port_uses_port_fallback(monkeypatch) -> None:
    monkeypatch.setenv('PAPERVISOR_PORT', 'invalid')
    monkeypatch.setenv('PORT', '8080')
    monkeypatch.delenv('PAPERVISOR_DB_PATH', raising=False)
    monkeypatch.delenv('PAPERVISOR_LIBRARY_DIR', raising=False)

    config._settings = None
    settings = config.get_settings()

    assert settings.port == 8080
