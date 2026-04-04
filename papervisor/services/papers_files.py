from __future__ import annotations

import os
import shutil
from pathlib import Path

from sqlalchemy import select

from papervisor.core.config import get_paths
from papervisor.core.exceptions import NotFoundException, ValidationException
from papervisor.db.models import Library, User
from sqlalchemy.orm import Session

from papervisor.db.session import get_session, use_session
from papervisor.services.patterns import get_pattern_settings, render_pattern, resolve_pattern_for, sanitize_rel_path


# Maximum byte length for a single path component (file or directory name).
# Most filesystems enforce 255 bytes; we leave headroom for dedup suffixes.
_NAME_MAX = 255
# Reserve bytes for UUID prefix (32 hex + dash = 33) and dedup suffix (e.g. " 999" = 4).
_SAFE_STEM_MAX = _NAME_MAX - 40  # 215 bytes — enough headroom for prefixes/suffixes


def _truncate_component(stem: str, suffix: str, max_bytes: int = _SAFE_STEM_MAX) -> str:
    """Truncate *stem* so that ``stem + suffix`` fits within *max_bytes* (UTF-8).

    The truncation is encode-aware: it never splits a multi-byte character.
    """
    max_stem_bytes = max_bytes - len(suffix.encode('utf-8'))
    if max_stem_bytes < 1:
        max_stem_bytes = 1
    encoded = stem.encode('utf-8')
    if len(encoded) <= max_stem_bytes:
        return stem
    # Truncate without splitting a multi-byte char.
    truncated = encoded[:max_stem_bytes].decode('utf-8', errors='ignore').rstrip()
    return truncated or 'file'


def move_file(src: Path, dest: Path) -> None:
    """Move a file to dest.

    Uses rename when possible, falls back to shutil.move for cross-device moves.
    """

    if src == dest:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.rename(dest)
    except Exception:
        shutil.move(str(src), str(dest))


def safe_filename(name: str) -> str:
    base = os.path.basename(name or '').strip() or 'upload'
    base = base.replace('\x00', '')
    stem, suffix = os.path.splitext(base)
    stem = _truncate_component(stem, suffix)
    return stem + suffix


def unique_path(folder: Path, filename: str) -> Path:
    candidate = folder / filename
    stem = candidate.stem
    suffix = candidate.suffix
    # Ensure the base name fits within NAME_MAX.
    stem = _truncate_component(stem, suffix)
    candidate = folder / (stem + suffix)
    if not candidate.exists():
        return candidate
    i = 1
    while True:
        dedup_suffix = f' {i}'
        truncated_stem = _truncate_component(stem, dedup_suffix + suffix)
        p = folder / f'{truncated_stem}{dedup_suffix}{suffix}'
        if not p.exists():
            return p
        i += 1


def unique_path_excluding(
    folder: Path,
    filename: str,
    *,
    exclude: Path | None,
    extra_excludes: list[Path] | tuple[Path, ...] | set[Path] | None = None,
) -> Path:
    candidate = folder / filename
    stem = candidate.stem
    suffix = candidate.suffix
    # Ensure the base name fits within NAME_MAX.
    stem = _truncate_component(stem, suffix)
    candidate = folder / (stem + suffix)

    excluded_paths: set[Path] = set()
    if exclude is not None:
        excluded_paths.add(exclude)
    if extra_excludes:
        excluded_paths.update(extra_excludes)

    if candidate in excluded_paths:
        return candidate
    if not candidate.exists():
        return candidate
    i = 1
    while True:
        dedup_suffix = f' {i}'
        truncated_stem = _truncate_component(stem, dedup_suffix + suffix)
        p = folder / f'{truncated_stem}{dedup_suffix}{suffix}'
        if p in excluded_paths:
            return p
        if not p.exists():
            return p
        i += 1


def sanitize_relative_path(rel: str) -> Path:
    return sanitize_rel_path(rel)


def library_root_for(library_id: str) -> Path:
    if not library_id:
        raise ValidationException('Library is required')

    with get_session() as session:
        lib = session.execute(select(Library).where(Library.id == library_id)).scalar_one_or_none()
        if lib is None:
            raise NotFoundException('Library not found')
        slug = lib.slug
        owner_id = lib.owner_user_id
        owner_username: str | None = None
        if owner_id is not None:
            u = session.get(User, int(owner_id))
            if u is not None:
                owner_username = str(u.username or '').strip() or None

    paths = get_paths()
    if owner_username:
        root = paths.library_files_dir / owner_username / slug
    else:
        root = paths.library_files_dir / slug
    root.mkdir(parents=True, exist_ok=True)
    return root


def pattern_target_path(
    *,
    library_id: str,
    file_type: str | None,
    current_path: Path,
    original_filename: str,
    title: str,
    authors: str | None,
    year: str | None,
    journal: str | None,
    publisher: str | None,
    isbn: str | None,
    series: str | None = None,
    series_index: str | None = None,
    language: str | None = None,
    exclude_paths: list[Path] | tuple[Path, ...] | set[Path] | None = None,
) -> Path:
    root = library_root_for(library_id)
    settings = get_pattern_settings()
    pattern = resolve_pattern_for(settings=settings, library_id=library_id, file_type=file_type)
    rendered = render_pattern(
        pattern,
        {
            'title': title or current_path.stem,
            'subtitle': '',
            'authors': authors or '',
            'year': year or '',
            'series': series or '',
            'seriesIndex': series_index or '',
            'language': language or '',
            'publisher': publisher or '',
            'isbn': isbn or '',
            'journal': journal or '',
            'currentFilename': original_filename or current_path.name,
        },
    )

    rendered = (rendered or '').strip() or current_path.stem
    rel = sanitize_relative_path(rendered)
    target_dir = (root / rel).parent
    target_dir.mkdir(parents=True, exist_ok=True)
    rendered_name = (root / rel).name or current_path.stem

    suffix = current_path.suffix
    if rendered_name.lower().endswith(suffix.lower()):
        target_name = rendered_name
    else:
        target_name = rendered_name + suffix

    return unique_path_excluding(
        target_dir,
        target_name,
        exclude=current_path,
        extra_excludes=exclude_paths,
    )
