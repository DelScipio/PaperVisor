from __future__ import annotations

import sys
from types import SimpleNamespace

sys.path.insert(0, '/home/pmmsoares/Documents/Python/PaperVisor')

from papervisor import static_mount
from papervisor.core import config as core_config


class _DummyApp:
    def __init__(self) -> None:
        self.routes = []
        self.mounted: list[tuple[str, str | None]] = []

    def mount(self, path: str, _handler, name: str | None = None) -> None:
        self.mounted.append((path, name))
        self.routes.append(SimpleNamespace(path=path))


def test_mount_static_warns_when_library_dir_missing(tmp_path, monkeypatch) -> None:
    dummy_app = _DummyApp()
    monkeypatch.setattr(static_mount, 'app', dummy_app)

    missing_library = tmp_path / 'missing-library'
    monkeypatch.setattr(
        core_config,
        'get_paths',
        lambda: SimpleNamespace(library_files_dir=missing_library),
    )

    warnings: list[str] = []
    monkeypatch.setattr(static_mount.logger, 'warning', lambda msg, *args: warnings.append(msg % args))

    static_mount.mount_static()

    assert ('/static', 'static') in dummy_app.mounted
    assert all(path != '/library_files' for path, _ in dummy_app.mounted)
    assert warnings
    assert 'library_files directory does not exist yet' in warnings[-1]
