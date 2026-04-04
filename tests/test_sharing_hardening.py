from __future__ import annotations

import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

sys.path.insert(0, '/home/pmmsoares/Documents/Python/PaperVisor')

from papervisor.core.exceptions import NotFoundException
from papervisor.services import sharing


def test_paper_storage_path_rejects_outside_library(tmp_path, monkeypatch) -> None:
    library_root = tmp_path / 'library'
    library_root.mkdir(parents=True)
    outside = tmp_path / 'outside.pdf'
    outside.write_bytes(b'pdf')

    monkeypatch.setattr(
        sharing,
        'get_paths',
        lambda: SimpleNamespace(library_files_dir=library_root),
    )

    row = SimpleNamespace(file_path=str(outside))
    with pytest.raises(NotFoundException):
        sharing._paper_storage_path(row)


def test_paper_storage_path_accepts_inside_library(tmp_path, monkeypatch) -> None:
    library_root = tmp_path / 'library'
    library_root.mkdir(parents=True)
    inside = library_root / 'paper.pdf'
    inside.write_bytes(b'pdf')

    monkeypatch.setattr(
        sharing,
        'get_paths',
        lambda: SimpleNamespace(library_files_dir=library_root),
    )

    row = SimpleNamespace(file_path=str(inside))
    resolved = sharing._paper_storage_path(row)
    assert resolved == inside.resolve()


def test_accept_library_share_triggers_cache_clear(monkeypatch) -> None:
    row = SimpleNamespace(status='pending', updated_at=None)

    class _ExecuteResult:
        def scalar_one_or_none(self):
            return row

    class _Session:
        def execute(self, _stmt):
            return _ExecuteResult()

        def commit(self):
            return None

    @contextmanager
    def _fake_get_session():
        yield _Session()

    monkeypatch.setattr(sharing, 'get_session', _fake_get_session)

    calls: list[str] = []
    monkeypatch.setattr(sharing, '_clear_reader_file_access_cache_best_effort', lambda: calls.append('clear'))

    sharing.accept_library_share(user_id=12, library_id='lib-1')

    assert calls == ['clear']


def test_decline_paper_share_triggers_cache_clear(monkeypatch) -> None:
    share = SimpleNamespace(shared_with_user_id=44, status='pending')

    class _Session:
        def get(self, _model, _share_id):
            return share

        def commit(self):
            return None

    @contextmanager
    def _fake_get_session():
        yield _Session()

    monkeypatch.setattr(sharing, 'get_session', _fake_get_session)

    calls: list[str] = []
    monkeypatch.setattr(sharing, '_clear_reader_file_access_cache_best_effort', lambda: calls.append('clear'))

    sharing.decline_paper_share(user_id=44, share_id=10)

    assert calls == ['clear']
