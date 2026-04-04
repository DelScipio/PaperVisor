from __future__ import annotations

from pathlib import Path

from papervisor.services.papers_files import unique_path, unique_path_excluding


def test_unique_path_adds_space_number_suffix_from_one(tmp_path: Path) -> None:
    existing = tmp_path / 'Title.pdf'
    existing.write_bytes(b'one')

    candidate = unique_path(tmp_path, 'Title.pdf')

    assert candidate == tmp_path / 'Title 1.pdf'


def test_unique_path_increments_suffix_when_needed(tmp_path: Path) -> None:
    (tmp_path / 'Title.pdf').write_bytes(b'one')
    (tmp_path / 'Title 1.pdf').write_bytes(b'two')

    candidate = unique_path(tmp_path, 'Title.pdf')

    assert candidate == tmp_path / 'Title 2.pdf'


def test_unique_path_excluding_skips_excluded_path(tmp_path: Path) -> None:
    base = tmp_path / 'Title.pdf'
    base.write_bytes(b'one')
    excluded = tmp_path / 'Title 1.pdf'
    excluded.write_bytes(b'two')

    candidate = unique_path_excluding(tmp_path, 'Title.pdf', exclude=excluded)

    assert candidate == excluded
