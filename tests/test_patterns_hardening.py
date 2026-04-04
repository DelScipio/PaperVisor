from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from papervisor.services import papers_import, patterns, sharing
from papervisor.services.patterns import PatternSettings
from papervisor.ui.pages.admin import patterns_panel


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value


def test_set_default_pattern_for_empty_removes_type_override(monkeypatch: pytest.MonkeyPatch) -> None:
    row = SimpleNamespace(pattern='old', updated_at=None)

    class _Session:
        def __init__(self):
            self.deleted = []
            self.commit_calls = 0

        def execute(self, _stmt):
            return _ScalarResult(row)

        def delete(self, obj):
            self.deleted.append(obj)

        def commit(self):
            self.commit_calls += 1

    session = _Session()

    @contextmanager
    def _fake_session_local():
        yield session

    monkeypatch.setattr(patterns, 'SessionLocal', _fake_session_local)

    patterns.set_default_pattern_for(file_type='paper', pattern='')

    assert session.deleted == [row]
    assert session.commit_calls == 1


def test_rename_papers_to_match_patterns_uses_series_and_language(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    current = tmp_path / 'source.epub'
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_bytes(b'book')

    row = SimpleNamespace(
        id='p-1',
        library_id='lib-1',
        file_path=str(current),
        file_type='book',
        title='Dune',
        subtitle='Part 1',
        authors='Frank Herbert',
        published_year='1965',
        series='Dune Saga',
        series_index='01',
        language='en',
        publisher='Ace',
        isbn='123',
        journal='',
    )

    captured_metadata: dict[str, str] = {}

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

        def scalars(self):
            return self

    class _Session:
        def __init__(self):
            self._calls = 0

        def execute(self, _stmt):
            self._calls += 1
            if self._calls == 1:
                return _Rows([('lib-1', 'books', 'alice')])
            return _Rows([row])

        def commit(self):
            return None

    @contextmanager
    def _fake_get_session():
        yield _Session()

    monkeypatch.setattr(papers_import, 'get_session', _fake_get_session)
    monkeypatch.setattr(
        papers_import,
        'get_paths',
        lambda: SimpleNamespace(library_files_dir=tmp_path / 'library'),
    )
    monkeypatch.setattr(
        papers_import,
        'get_pattern_settings',
        lambda: PatternSettings(default_paper_pattern='{title}', default_book_pattern='{title}', library_overrides={}),
    )
    monkeypatch.setattr(papers_import, 'resolve_pattern_for', lambda **_kwargs: '{title}')

    def _capture_render(_pattern: str, metadata: dict[str, str]) -> str:
        captured_metadata.update(metadata)
        return 'target'

    monkeypatch.setattr(papers_import, 'render_pattern', _capture_render)
    monkeypatch.setattr(papers_import, 'unique_path_excluding', lambda _folder, _name, exclude=None: exclude)
    monkeypatch.setattr(papers_import, 'move_file', lambda _src, _dest: None)

    result = papers_import.rename_papers_to_match_patterns(library_ids=['lib-1'])

    assert result.processed == 1
    assert captured_metadata['series'] == 'Dune Saga'
    assert captured_metadata['seriesIndex'] == '01'
    assert captured_metadata['language'] == 'en'


def test_copy_shared_paper_to_library_applies_destination_pattern(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / 'origin.pdf'
    src.write_bytes(b'pdf')

    share_row = SimpleNamespace(status='pending', shared_with_user_id=7, paper_id='paper-1')
    paper_row = SimpleNamespace(
        id='paper-1',
        file_type='paper',
        title='My Paper',
        subtitle='A subtitle',
        doi='10.1/abc',
        authors='Ada Lovelace',
        published_year='1843',
        journal='Journal',
        publisher='Publisher',
        isbn='isbn',
        description='desc',
        language='en',
        genres='cs',
        publication_date='1843-01-01',
        series='Series',
        series_index='01',
        page_count=10,
        abstract='abs',
        url='https://example.org',
        volume='1',
        issue='2',
        pages='1-10',
        keywords='kw',
        file_path=str(src),
    )
    target_library = SimpleNamespace(id='lib-1', owner_user_id=7, slug='target')

    class _Session:
        def __init__(self):
            self.added = []

        def get(self, model, key):
            if model is sharing.PaperShare:
                return share_row
            if model is sharing.Paper:
                return paper_row
            if model is sharing.Library:
                return target_library
            return None

        def add(self, row):
            self.added.append(row)

        def commit(self):
            return None

    session = _Session()

    @contextmanager
    def _fake_get_session():
        yield session

    monkeypatch.setattr(sharing, 'get_session', _fake_get_session)
    monkeypatch.setattr(sharing, '_paper_storage_path', lambda _paper: src)
    monkeypatch.setattr(sharing, '_library_owner_username', lambda **_kwargs: 'alice')
    monkeypatch.setattr(sharing, 'get_paths', lambda: SimpleNamespace(library_files_dir=tmp_path / 'library'))

    from papervisor.services import papers_files

    target_path = tmp_path / 'library' / 'alice' / 'target' / 'by-pattern.pdf'
    monkeypatch.setattr(papers_files, 'pattern_target_path', lambda **_kwargs: target_path)
    monkeypatch.setattr(papers_files, 'move_file', lambda src_path, dest_path: Path(src_path).rename(dest_path))

    new_id = sharing.copy_shared_paper_to_library(user_id=7, share_id=10, target_library_id='lib-1')

    assert isinstance(new_id, str) and new_id
    assert share_row.status == 'accepted'
    created = session.added[0]
    assert str(created.file_path) == str(target_path)
    assert str(created.title) == 'My Paper'
    assert target_path.exists()


def test_admin_patterns_panel_hides_library_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        patterns_panel,
        'get_pattern_settings',
        lambda: PatternSettings(default_paper_pattern='{title}', default_book_pattern='{title}', library_overrides={}),
    )
    monkeypatch.setattr(patterns_panel, 'list_libraries', lambda owner_user_id=None: [])

    def _fake_render_patterns_editor(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(patterns_panel, 'render_patterns_editor', _fake_render_patterns_editor)

    patterns_panel.render_patterns_panel(current_user_id=1)

    assert captured['show_library_overrides'] is False
    assert captured['libraries'] == []
    assert captured['on_save_overrides'] is None
