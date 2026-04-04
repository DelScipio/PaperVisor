from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from papervisor.db.models import LibraryNamingPattern, NamingPattern
from papervisor.db.session import SessionLocal


DEFAULT_DEFAULT_PATTERN = '{authors}/<{series}>/<{seriesIndex}> {title}< - {authors}>< ({year})>'


PLACEHOLDERS: dict[str, str] = {
    'title': 'Book/Paper title',
    'subtitle': 'Book/Paper subtitle',
    'authors': 'Author(s) (formatted as “First et al”)',
    'year': 'Full year (e.g. 2025)',
    'series': 'Series name',
    'seriesIndex': 'Series index (e.g. 01)',
    'language': 'Language code (e.g. en)',
    'publisher': 'Publisher name',
    'isbn': 'ISBN number',
    'journal': 'Journal / venue',
    'currentFilename': 'Original file name (with extension)',
}

_OPTIONAL_BLOCK_RE = re.compile(r'<([^<>]*)>')
_PLACEHOLDER_RE = re.compile(r'\{([a-zA-Z0-9_]+)\}')


def _normalize_pattern_value(pattern: str) -> str:
    # Delegate to the shared NUL-stripping helper.
    from papervisor.core.sanitizers import clean_nul
    return clean_nul(pattern)


def _validate_pattern_value(pattern: str) -> str:
    pat = _normalize_pattern_value(pattern)
    # DB column is String(1024) but SQLite won't enforce it; guard here.
    if len(pat) > 1024:
        raise ValueError('Pattern is too long (max 1024 characters)')
    return pat


# Maximum byte length for a single path component.
_COMPONENT_MAX_BYTES = 240  # leaves room for dedup suffixes added later


def _truncate_path_component(component: str, *, preserve_ext: bool = False) -> str:
    """Truncate a single path component to fit within ``_COMPONENT_MAX_BYTES`` (UTF-8).

    When *preserve_ext* is True the file extension is kept intact and only the
    stem is shortened.
    """
    if len(component.encode('utf-8')) <= _COMPONENT_MAX_BYTES:
        return component

    if preserve_ext:
        import os
        stem, ext = os.path.splitext(component)
        max_stem = _COMPONENT_MAX_BYTES - len(ext.encode('utf-8'))
        if max_stem < 1:
            max_stem = 1
        truncated = stem.encode('utf-8')[:max_stem].decode('utf-8', errors='ignore').rstrip()
        return (truncated or 'file') + ext

    truncated = component.encode('utf-8')[:_COMPONENT_MAX_BYTES].decode('utf-8', errors='ignore').rstrip()
    return truncated or 'file'


def sanitize_rel_path(rendered: str) -> Path:
    """Sanitize a rendered pattern into a safe relative path.

    This matches the behavior used when actually moving/renaming files.
    Each path component is truncated to ``_COMPONENT_MAX_BYTES`` bytes to
    respect filesystem ``NAME_MAX`` limits.
    """

    rel = (rendered or '').replace('\\', '/').strip()
    parts: list[str] = []
    for part in rel.split('/'):
        part = part.strip().strip('.')
        if not part:
            continue
        part = ''.join(c for c in part if c not in '<>:\\|?*')
        if part:
            parts.append(part)

    if not parts:
        return Path('')

    # Truncate each component; preserve extension on the final (filename) part.
    for i, p in enumerate(parts):
        is_last = i == len(parts) - 1
        parts[i] = _truncate_path_component(p, preserve_ext=is_last)

    return Path(*parts)


@dataclass(frozen=True)
class PatternSettings:
    default_paper_pattern: str
    default_book_pattern: str
    # library_id -> file_type -> pattern
    library_overrides: dict[str, dict[str, str]]


def _norm_file_type(file_type: str | None) -> str:
    ft = str(file_type or '').strip().lower()
    return ft if ft in {'paper', 'book'} else 'paper'


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def format_authors_et_al(authors: str | list[str] | None) -> str:
    if authors is None:
        return ''

    if isinstance(authors, list):
        parts = [a.strip() for a in authors if str(a).strip()]
    else:
        raw = str(authors).strip()
        if not raw:
            return ''
        if ';' in raw:
            parts = [p.strip() for p in raw.split(';') if p.strip()]
        else:
            parts = [p.strip() for p in raw.split(',') if p.strip()]

    if not parts:
        return ''
    if len(parts) == 1:
        return parts[0]
    return f'{parts[0]} et al'


def _replace_placeholders(text: str, values: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        val = values.get(key, '')
        # Replace forward slashes so values like titles ("A/B/C") don't
        # accidentally create subdirectories when used in a file-path pattern.
        return val.replace('/', '-')

    return _PLACEHOLDER_RE.sub(repl, text)


def render_pattern(pattern: str, metadata: dict[str, str]) -> str:
    values = dict(metadata)
    values['authors'] = format_authors_et_al(values.get('authors'))

    out = str(pattern or '')

    def eval_optional(block: str) -> str:
        keys = _PLACEHOLDER_RE.findall(block)
        for key in keys:
            if not str(values.get(key, '')).strip():
                return ''
        return _replace_placeholders(block, values)

    while True:
        match = _OPTIONAL_BLOCK_RE.search(out)
        if not match:
            break
        out = out[: match.start()] + eval_optional(match.group(1)) + out[match.end() :]

    out = _replace_placeholders(out, values)
    out = re.sub(r'\s+', ' ', out).strip()
    out = out.replace(' /', '/').replace('/ ', '/')
    # Avoid leaking optional syntax if user types unmatched brackets.
    out = out.replace('<', '').replace('>', '')
    return out


def _get_or_create_pattern(session, *, key: str, default_value: str) -> NamingPattern:
    existing = session.execute(select(NamingPattern).where(NamingPattern.key == key)).scalar_one_or_none()
    if existing is not None:
        return existing

    row = NamingPattern(key=key, pattern=default_value, updated_at=_now_utc())
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        # Another request likely created it concurrently.
        session.rollback()
        existing = session.execute(select(NamingPattern).where(NamingPattern.key == key)).scalar_one()
        return existing
    session.refresh(row)
    return row


def get_pattern_settings() -> PatternSettings:
    # Backward compatible:
    # - global default used to be key='default'
    # - now we support key='default.paper' and key='default.book'
    with SessionLocal() as session:
        base_default = _get_or_create_pattern(
            session,
            key='default',
            default_value=DEFAULT_DEFAULT_PATTERN,
        ).pattern
        default_paper = _get_or_create_pattern(
            session,
            key='default.paper',
            default_value=str(base_default or DEFAULT_DEFAULT_PATTERN),
        ).pattern
        default_book = _get_or_create_pattern(
            session,
            key='default.book',
            default_value=str(base_default or DEFAULT_DEFAULT_PATTERN),
        ).pattern

        overrides = session.execute(select(LibraryNamingPattern)).scalars().all()

    by_lib: dict[str, dict[str, str]] = {}
    for o in overrides:
        lib_id = str(getattr(o, 'library_id', '') or '').strip()
        if not lib_id:
            continue
        ft = _norm_file_type(getattr(o, 'file_type', None))
        pat = str(getattr(o, 'pattern', '') or '').strip()
        if not pat:
            continue
        by_lib.setdefault(lib_id, {})[ft] = pat

    return PatternSettings(
        default_paper_pattern=str(default_paper or base_default),
        default_book_pattern=str(default_book or base_default),
        library_overrides=by_lib,
    )


def resolve_pattern_for(*, settings: PatternSettings, library_id: str | None, file_type: str | None) -> str:
    ft = _norm_file_type(file_type)
    lib_id = str(library_id or '').strip()
    if lib_id:
        lib_map = settings.library_overrides.get(lib_id) or {}
        p = str(lib_map.get(ft) or '').strip()
        if p:
            return p
    return settings.default_book_pattern if ft == 'book' else settings.default_paper_pattern


def set_default_pattern(pattern: str) -> None:
    """Back-compat: set both paper+book defaults to the same value."""
    set_default_pattern_for(file_type='paper', pattern=pattern)
    set_default_pattern_for(file_type='book', pattern=pattern)
    # Keep legacy key updated as well.
    pattern = _validate_pattern_value(pattern)
    with SessionLocal() as session:
        row = session.execute(select(NamingPattern).where(NamingPattern.key == 'default')).scalar_one_or_none()
        if row is None:
            row = NamingPattern(key='default', pattern=pattern, updated_at=_now_utc())
            session.add(row)
        else:
            row.pattern = pattern
            row.updated_at = _now_utc()
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            row = session.execute(select(NamingPattern).where(NamingPattern.key == 'default')).scalar_one()
            row.pattern = pattern
            row.updated_at = _now_utc()
            session.commit()


def set_default_pattern_for(*, file_type: str, pattern: str) -> None:
    normalized = _normalize_pattern_value(pattern or '')
    if normalized:
        normalized = _validate_pattern_value(normalized)
    ft = _norm_file_type(file_type)
    key = f'default.{ft}'
    with SessionLocal() as session:
        row = session.execute(select(NamingPattern).where(NamingPattern.key == key)).scalar_one_or_none()
        if not normalized:
            if row is not None:
                session.delete(row)
                session.commit()
            return

        if row is None:
            row = NamingPattern(key=key, pattern=normalized, updated_at=_now_utc())
            session.add(row)
        else:
            row.pattern = normalized
            row.updated_at = _now_utc()
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            row = session.execute(select(NamingPattern).where(NamingPattern.key == key)).scalar_one()
            row.pattern = normalized
            row.updated_at = _now_utc()
            session.commit()


def set_library_override(*, library_id: str, pattern: str | None) -> None:
    """Back-compat: set both paper+book overrides to the same value."""
    set_library_override_for(library_id=str(library_id), file_type='paper', pattern=pattern)
    set_library_override_for(library_id=str(library_id), file_type='book', pattern=pattern)


def set_library_override_for(*, library_id: str, file_type: str, pattern: str | None) -> None:
    pattern = _normalize_pattern_value(pattern or '')
    ft = _norm_file_type(file_type)
    if pattern:
        pattern = _validate_pattern_value(pattern)
    with SessionLocal() as session:
        row = session.execute(
            select(LibraryNamingPattern)
            .where(LibraryNamingPattern.library_id == str(library_id))
            .where(LibraryNamingPattern.file_type == ft)
        ).scalar_one_or_none()

        if not pattern:
            if row is not None:
                session.delete(row)
                session.commit()
            return

        if row is None:
            row = LibraryNamingPattern(library_id=str(library_id), file_type=ft, pattern=pattern, updated_at=_now_utc())
            session.add(row)
        else:
            row.pattern = pattern
            row.updated_at = _now_utc()
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            row = session.execute(
                select(LibraryNamingPattern)
                .where(LibraryNamingPattern.library_id == str(library_id))
                .where(LibraryNamingPattern.file_type == ft)
            ).scalar_one()
            row.pattern = pattern
            row.updated_at = _now_utc()
            session.commit()
