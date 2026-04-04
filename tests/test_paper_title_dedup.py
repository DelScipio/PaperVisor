from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import shutil

from papervisor.services import papers_import
from papervisor.services.patterns import PatternSettings


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self


def test_commit_staged_import_keeps_db_title_when_filename_is_deduped(
    monkeypatch,
    tmp_path: Path,
) -> None:
    library_root = tmp_path / 'library'
    library_root.mkdir(parents=True, exist_ok=True)
    staged = tmp_path / 'staged.pdf'
    staged.write_bytes(b'pdf')

    # Force a collision at the pattern target so final file becomes "Title 1.pdf".
    (library_root / 'Title.pdf').write_bytes(b'existing')

    monkeypatch.setattr(papers_import, '_refresh_preview_assets_after_upload', lambda **_kwargs: None)
    monkeypatch.setattr(
        papers_import,
        'extract_import_metadata',
        lambda **_kwargs: SimpleNamespace(
            metadata_ok=True,
            title='Title',
            doi=None,
            authors=None,
            year=None,
            journal=None,
            publisher=None,
            isbn=None,
            description=None,
            language=None,
            genres=None,
            publication_date=None,
            series=None,
            series_index=None,
            page_count=None,
            abstract=None,
            url=None,
            volume=None,
            issue=None,
            pages=None,
            keywords=None,
        ),
    )
    monkeypatch.setattr(papers_import, 'get_pattern_settings', lambda: PatternSettings('', '', {}))
    monkeypatch.setattr(papers_import, 'resolve_pattern_for', lambda **_kwargs: '{title}')
    monkeypatch.setattr(papers_import, 'render_pattern', lambda _pattern, _metadata: 'Title')

    from papervisor.services import papers_files

    monkeypatch.setattr(papers_files, 'library_root_for', lambda _library_id: library_root)

    captured: dict[str, object] = {}

    def _fake_create_paper_record(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id='paper-1')

    monkeypatch.setattr(papers_import, 'create_paper_record', _fake_create_paper_record)

    result = papers_import.commit_staged_import(
        library_id='lib-1',
        file_type='paper',
        staged_path=str(staged),
        original_filename='upload.pdf',
    )

    assert result.saved_path.name == 'Title 1.pdf'
    assert captured['title'] == 'Title'


def test_rename_papers_to_match_patterns_syncs_db_title_with_deduped_filename(
    monkeypatch,
    tmp_path: Path,
) -> None:
    current = tmp_path / 'source.pdf'
    current.write_bytes(b'new')

    target_dir = tmp_path / 'library' / 'alice' / 'books'
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / 'Title.pdf').write_bytes(b'existing')

    row = SimpleNamespace(
        id='p-1',
        library_id='lib-1',
        file_path=str(current),
        file_type='paper',
        title='Old Title',
        subtitle='',
        authors='',
        published_year='',
        series='',
        series_index='',
        language='',
        publisher='',
        isbn='',
        journal='',
    )

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
    monkeypatch.setattr(papers_import, 'get_paths', lambda: SimpleNamespace(library_files_dir=tmp_path / 'library'))
    monkeypatch.setattr(papers_import, 'get_pattern_settings', lambda: PatternSettings('{title}', '{title}', {}))
    monkeypatch.setattr(papers_import, 'resolve_pattern_for', lambda **_kwargs: '{title}')
    monkeypatch.setattr(papers_import, 'render_pattern', lambda _pattern, _metadata: 'Title')

    result = papers_import.rename_papers_to_match_patterns(library_ids=['lib-1'])

    assert result.renamed == 1
    assert Path(str(row.file_path)).name == 'Title 1.pdf'
    assert row.title == 'Old Title'


def test_replace_file_reuses_same_name_without_self_dedup(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / 'library' / 'alice' / 'books'
    root.mkdir(parents=True, exist_ok=True)

    old_file = root / 'Title.pdf'
    old_file.write_bytes(b'old')

    staged = tmp_path / 'staged.pdf'
    staged.write_bytes(b'new')

    row = SimpleNamespace(
        id='p-1',
        library_id='lib-1',
        file_type='paper',
        file_path=str(old_file),
        title='Title',
        authors='',
        published_year='',
        journal='',
        publisher='',
        isbn='',
    )

    class _Session:
        def get(self, model, key):
            if key == 'p-1':
                return row
            return None

        def commit(self):
            return None

        def refresh(self, _row):
            return None

    @contextmanager
    def _fake_get_session():
        yield _Session()

    monkeypatch.setattr(papers_import, 'get_session', _fake_get_session)
    monkeypatch.setattr(papers_import, '_refresh_preview_assets_after_upload', lambda **_kwargs: None)
    from papervisor.services import papers_files

    monkeypatch.setattr(papers_files, 'library_root_for', lambda _library_id: root)
    monkeypatch.setattr(papers_files, 'get_pattern_settings', lambda: PatternSettings('', '', {}))
    monkeypatch.setattr(papers_files, 'resolve_pattern_for', lambda **_kwargs: '{title}')
    monkeypatch.setattr(papers_files, 'render_pattern', lambda _pattern, _metadata: 'Title')
    monkeypatch.setattr(papers_import, 'safe_filename', lambda _name: 'Title.pdf')
    monkeypatch.setattr(shutil, 'move', lambda src, dst: Path(src).rename(dst))

    imported = papers_import.attach_staged_file_to_paper(
        paper_id='p-1',
        staged_path=str(staged),
        original_filename='Title.pdf',
        library_id='lib-1',
        file_type='paper',
    )

    assert imported.saved_path.name == 'Title.pdf'
    assert Path(str(row.file_path)).name == 'Title.pdf'
    assert old_file.exists()
