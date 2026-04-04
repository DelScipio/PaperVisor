from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Integer, case, exists, select, true
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from papervisor.db.models import (
    Library,
    LibraryShare,
    Paper,
    PaperFavorite,
    PaperMarker,
    PaperTag,
    PaperToRead,
    Tag,
)

from papervisor.db.session import get_session, use_session
from papervisor.domain import PaperItem


# Soft-delete filter: reusable clause to exclude trashed papers.
_NOT_DELETED = Paper.deleted_at.is_(None)


@dataclass(frozen=True)
class PaperFilters:
    """Filters used by the UI list/search views.

    Keep this intentionally small and DB-backed.
    """

    file_type: str | None = None  # 'paper' | 'book' | None
    favorites_only: bool = False
    to_read_only: bool = False
    has_doi: bool = False
    has_isbn: bool = False
    missing_id: bool = False
    completed_only: bool = False
    tag_names: list[str] | None = None
    marker_ids: list[str] | None = None
    year_min: int | None = None
    year_max: int | None = None

    # Facet-like filters (exact/contains match, depending on field)
    authors: list[str] | None = None
    journals: list[str] | None = None
    publishers: list[str] | None = None
    series: list[str] | None = None
    languages: list[str] | None = None
    genres: list[str] | None = None


_SEARCH_MODE_ALIASES: dict[str, str] = {
    'all': 'all',
    'any': 'all',
    'title': 'title',
    'titles': 'title',
    'author': 'authors',
    'authors': 'authors',
    'publisher': 'publisher',
    'publishers': 'publisher',
    'journal': 'journal',
    'journals': 'journal',
    'tag': 'tags',
    'tags': 'tags',
    'doi': 'doi',
    'isbn': 'isbn',
}


def _normalize_search_mode(mode: str | None) -> str:
    raw = str(mode or 'all').strip().lower()
    return _SEARCH_MODE_ALIASES.get(raw, 'all')


def _escape_like(value: str) -> str:
    return str(value).translate(str.maketrans({'%': '\\%', '_': '\\_', '\\': '\\\\'}))


def _search_scope_clause(*, query: str, mode: str) -> ColumnElement[bool]:
    q = str(query or '').strip().lower()
    if not q:
        return true()

    q_escaped = _escape_like(q)

    def _like(col: Any) -> ColumnElement[bool]:
        return func.lower(func.coalesce(col, '')).like(f'%{q_escaped}%', escape='\\')

    mode_key = _normalize_search_mode(mode)
    tag_match = exists(
        select(1)
        .select_from(PaperTag)
        .join(Tag, Tag.id == PaperTag.tag_id)
        .where(PaperTag.paper_id == Paper.id)
        .where(func.lower(func.coalesce(Tag.name, '')).like(f'%{q_escaped}%', escape='\\'))
    )

    if mode_key == 'tags':
        return tag_match
    if mode_key == 'title':
        return or_(_like(Paper.title), _like(Paper.subtitle))
    if mode_key == 'authors':
        return _like(Paper.authors)
    if mode_key == 'publisher':
        return _like(Paper.publisher)
    if mode_key == 'journal':
        return _like(Paper.journal)
    if mode_key == 'doi':
        return _like(Paper.doi)
    if mode_key == 'isbn':
        return _like(Paper.isbn)

    return or_(
        _like(Paper.title),
        _like(Paper.subtitle),
        _like(Paper.authors),
        _like(Paper.publisher),
        _like(Paper.journal),
        _like(Paper.series),
        _like(Paper.language),
        _like(Paper.genres),
        _like(Paper.doi),
        _like(Paper.isbn),
        _like(Paper.file_path),
        _like(Paper.keywords),
        tag_match,
    )


def _accessible_library_ids_subquery(*, user_id: int) -> Select[tuple[str]]:
    uid = int(user_id)
    shared_subq = (
        select(LibraryShare.library_id)
        .where(LibraryShare.shared_with_user_id == uid)
        .where(LibraryShare.status == 'accepted')
    )
    return (
        select(Library.id)
        .where(
            or_(
                Library.owner_user_id == uid,
                Library.scope == 'global',
                Library.id.in_(shared_subq),
            )
        )
    )


def _favorite_ids_for(*, session: Session, user_id: int, paper_ids: list[str]) -> set[str]:
    if not paper_ids:
        return set()
    rows = session.execute(
        select(PaperFavorite.paper_id)
        .where(PaperFavorite.user_id == int(user_id))
        .where(PaperFavorite.paper_id.in_(paper_ids))
    ).scalars().all()
    return {str(x) for x in rows}


def _to_read_ids_for(*, session: Session, user_id: int, paper_ids: list[str]) -> set[str]:
    if not paper_ids:
        return set()
    rows = session.execute(
        select(PaperToRead.paper_id)
        .where(PaperToRead.user_id == int(user_id))
        .where(PaperToRead.paper_id.in_(paper_ids))
    ).scalars().all()
    return {str(x) for x in rows}


def is_favorite(*, user_id: int, paper_id: str) -> bool:
    if not paper_id:
        return False
    with get_session() as session:
        row = session.execute(
            select(PaperFavorite.paper_id)
            .where(PaperFavorite.user_id == int(user_id))
            .where(PaperFavorite.paper_id == str(paper_id))
            .limit(1)
        ).scalar_one_or_none()
        return row is not None


def is_to_read(*, user_id: int, paper_id: str) -> bool:
    if not paper_id:
        return False
    with get_session() as session:
        row = session.execute(
            select(PaperToRead.paper_id)
            .where(PaperToRead.user_id == int(user_id))
            .where(PaperToRead.paper_id == str(paper_id))
            .limit(1)
        ).scalar_one_or_none()
        return row is not None


def list_paper_filter_facets(
    *,
    user_id: int | None = None,
    library_id: str | None = None,
    library_ids: list[str] | None = None,
    file_type: str | None = None,
    limit: int = 50,
) -> dict[str, list[tuple[str, int]]]:
    """Return facet-like value counts for the Filters drawer.

    - Most facets group by raw stored string values.
    - Authors/genres are tokenized so the UI is usable.
    - For papers, authors uses only the first author.
    """

    ft = str(file_type or '').strip().lower() or None
    if ft not in {None, 'paper', 'book'}:
        ft = None

    def _has_text(col: Any) -> Any:
        return func.length(func.trim(func.coalesce(col, ''))) > 0

    def _norm_ids(values: list[str] | None) -> list[str]:
        out: list[str] = []
        for v in values or []:
            s = str(v or '').strip()
            if s:
                out.append(s)
        return out

    lib_ids = _norm_ids(library_ids)
    if library_id and str(library_id).strip():
        # Backward compatible: single library_id wins.
        lib_ids = [str(library_id).strip()]

    def _split_tokens(value: str) -> list[str]:
        s = str(value or '').strip()
        if not s:
            return []

        # Normalize common separators (authors/genres tend to be messy).
        s = s.replace('\n', ';')
        s = s.replace('|', ';')
        s = s.replace('/', ';')
        s = re.sub(r'\s+and\s+', ';', s, flags=re.IGNORECASE)
        s = re.sub(r'\s*&\s*', ';', s)

        parts = re.split(r'\s*[,;]+\s*', s)
        out: list[str] = []
        for p in parts:
            p = str(p or '').strip()
            if p:
                out.append(p)
        return out

    def _token_facet(*, session: Session, col_name: str, first_only: bool = False) -> list[tuple[str, int]]:
        # Pull raw strings then tokenize in Python.
        col = getattr(Paper, col_name)
        stmt = select(col).select_from(Paper).where(_NOT_DELETED)

        if lib_ids:
            stmt = stmt.where(Paper.library_id.in_(lib_ids))

        if user_id is not None:
            allowed = _accessible_library_ids_subquery(user_id=int(user_id))
            stmt = stmt.where(Paper.library_id.in_(allowed))

        if ft:
            stmt = stmt.where(Paper.file_type == ft)

        stmt = stmt.where(_has_text(col))
        rows = session.execute(stmt).scalars().all()

        counts: dict[str, int] = {}
        for raw in rows:
            tokens = _split_tokens(str(raw or ''))
            if not tokens:
                continue
            if first_only:
                tokens = tokens[:1]
            for t in tokens:
                key = t.strip()
                if not key:
                    continue
                counts[key] = int(counts.get(key, 0)) + 1

        items = list(counts.items())
        items.sort(key=lambda kv: (-int(kv[1]), kv[0].lower()))
        return [(k, int(v)) for (k, v) in items[: int(limit)]]

    def _facet(session: Session, col: Any) -> list[tuple[str, int]]:
        stmt = select(func.trim(func.coalesce(col, '')).label('v'), func.count(Paper.id).label('c')).select_from(Paper).where(_NOT_DELETED)

        if lib_ids:
            stmt = stmt.where(Paper.library_id.in_(lib_ids))

        if user_id is not None:
            allowed = _accessible_library_ids_subquery(user_id=int(user_id))
            stmt = stmt.where(Paper.library_id.in_(allowed))

        if ft:
            stmt = stmt.where(Paper.file_type == ft)

        stmt = (
            stmt.where(_has_text(col))
            .group_by(func.trim(func.coalesce(col, '')))
            .order_by(func.count(Paper.id).desc(), func.lower(func.trim(func.coalesce(col, ''))).asc())
            .limit(int(limit))
        )

        rows = session.execute(stmt).all()
        return [(str(v), int(c or 0)) for (v, c) in rows if str(v).strip()]

    with get_session() as session:
        return {
            'authors': _token_facet(session=session, col_name='authors', first_only=True),
            'journal': _facet(session, Paper.journal),
            'publisher': _facet(session, Paper.publisher),
            'series': _facet(session, Paper.series),
            'language': _facet(session, Paper.language),
            'genres': _token_facet(session=session, col_name='genres', first_only=False),
        }


def list_papers(*, user_id: int | None = None, library_id: str | None = None, limit: int | None = 50) -> list[PaperItem]:
    with get_session() as session:
        # Default sorting is configurable via Admin → Library.
        try:
            from papervisor.services.settings import get_default_sort

            sort_key = get_default_sort()
        except Exception:
            sort_key = 'recent'

        if sort_key == 'title_asc':
            stmt = select(Paper).where(_NOT_DELETED).order_by(Paper.title.asc(), Paper.created_at.desc())
        elif sort_key == 'title_desc':
            stmt = select(Paper).where(_NOT_DELETED).order_by(Paper.title.desc(), Paper.created_at.desc())
        else:
            stmt = select(Paper).where(_NOT_DELETED).order_by(Paper.created_at.desc())
        if library_id:
            stmt = stmt.where(Paper.library_id == library_id)

        if user_id is not None:
            allowed = _accessible_library_ids_subquery(user_id=int(user_id))
            stmt = stmt.where(Paper.library_id.in_(allowed))

        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)

        rows = session.execute(stmt).scalars().all()

        fav_ids: set[str] = set()
        to_read_ids: set[str] = set()
        if user_id is not None and rows:
            ids = [str(r.id) for r in rows]
            fav_ids = _favorite_ids_for(session=session, user_id=int(user_id), paper_ids=ids)
            to_read_ids = _to_read_ids_for(session=session, user_id=int(user_id), paper_ids=ids)

        return [
            PaperItem(
                id=r.id,
                title=r.title,
                subtitle=r.subtitle or '',
                reading_progress=float(r.reading_progress or 0.0),
                is_completed=bool(r.is_completed),
                is_favorite=(str(r.id) in fav_ids) if user_id is not None else False,
                is_to_read=(str(r.id) in to_read_ids) if user_id is not None else False,
                open_count_total=int(r.open_count_total or 0),
                open_count_since_reset=int(r.open_count_since_reset or 0),
                file_suffix=Path(str(r.file_path or '')).suffix if r.file_path else '',
                file_type=str(r.file_type or "paper"),
            )
            for r in rows
        ]


def list_recent_papers(
    *,
    user_id: int | None = None,
    library_id: str | None = None,
    limit: int | None = 50,
) -> list[PaperItem]:
    """List most recently added papers.

    This is intentionally independent of the Admin default sort setting.
    """
    with get_session() as session:
        stmt = select(Paper).where(_NOT_DELETED).order_by(Paper.created_at.desc())
        if library_id:
            stmt = stmt.where(Paper.library_id == library_id)

        if user_id is not None:
            allowed = _accessible_library_ids_subquery(user_id=int(user_id))
            stmt = stmt.where(Paper.library_id.in_(allowed))

        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)

        rows = session.execute(stmt).scalars().all()

        fav_ids: set[str] = set()
        to_read_ids: set[str] = set()
        if user_id is not None and rows:
            ids = [str(r.id) for r in rows]
            fav_ids = _favorite_ids_for(session=session, user_id=int(user_id), paper_ids=ids)
            to_read_ids = _to_read_ids_for(session=session, user_id=int(user_id), paper_ids=ids)

        return [
            PaperItem(
                id=r.id,
                title=r.title,
                subtitle=r.subtitle or '',
                reading_progress=float(r.reading_progress or 0.0),
                is_completed=bool(r.is_completed),
                is_favorite=(str(r.id) in fav_ids) if user_id is not None else False,
                is_to_read=(str(r.id) in to_read_ids) if user_id is not None else False,
                open_count_total=int(r.open_count_total or 0),
                open_count_since_reset=int(r.open_count_since_reset or 0),
                file_suffix=Path(str(r.file_path or '')).suffix if r.file_path else '',
                file_type=str(r.file_type or "paper"),
            )
            for r in rows
        ]


def search_papers(
    *,
    query: str,
    mode: str = 'all',
    user_id: int | None = None,
    library_id: str | None = None,
    limit: int = 500,
) -> list[PaperItem]:
    q = str(query or '').strip()
    if not q:
        return []
    mode_key = _normalize_search_mode(mode)

    with get_session() as session:
        stmt = select(Paper).where(_NOT_DELETED)
        if library_id:
            stmt = stmt.where(Paper.library_id == library_id)

        if user_id is not None:
            allowed = _accessible_library_ids_subquery(user_id=int(user_id))
            stmt = stmt.where(Paper.library_id.in_(allowed))

        stmt = stmt.where(_search_scope_clause(query=q, mode=mode_key))

        stmt = stmt.order_by(Paper.created_at.desc()).limit(int(limit))
        rows = session.execute(stmt).scalars().all()

        fav_ids: set[str] = set()
        to_read_ids: set[str] = set()
        if user_id is not None and rows:
            ids = [str(r.id) for r in rows]
            fav_ids = _favorite_ids_for(session=session, user_id=int(user_id), paper_ids=ids)
            to_read_ids = _to_read_ids_for(session=session, user_id=int(user_id), paper_ids=ids)

    return [
        PaperItem(
            id=r.id,
            title=r.title,
            subtitle=r.subtitle or '',
            reading_progress=float(r.reading_progress or 0.0),
            is_completed=bool(r.is_completed),
            is_favorite=(str(r.id) in fav_ids) if user_id is not None else False,
            is_to_read=(str(r.id) in to_read_ids) if user_id is not None else False,
            open_count_total=int(r.open_count_total or 0),
            open_count_since_reset=int(r.open_count_since_reset or 0),
            file_suffix=Path(str(r.file_path or '')).suffix if r.file_path else '',
                file_type=str(r.file_type or "paper"),
        )
        for r in rows
    ]


def _apply_paper_filters(
    stmt: Select,  # type: ignore[type-arg]
    *,
    user_id: int | None = None,
    library_id: str | None = None,
    library_ids: list[str] | None = None,
    query: str | None = None,
    mode: str = 'all',
    filters: PaperFilters | None = None,
) -> Select:  # type: ignore[type-arg]
    """Apply shared WHERE-clause logic for paper listing and counting.

    Returns the *modified* SELECT statement with all filters applied
    (but no ORDER BY, LIMIT, or OFFSET).
    """

    f = filters or PaperFilters()
    ft = str(f.file_type or '').strip().lower() or None
    if ft not in {None, 'paper', 'book'}:
        ft = None

    q = str(query or '').strip()

    def _has_text(col: Any) -> Any:
        return func.length(func.trim(func.coalesce(col, ''))) > 0

    def _norm_list(values: list[str] | None) -> list[str]:
        if not values:
            return []
        return [str(v).strip() for v in values if str(v or '').strip()]

    def _norm_ids(values: list[str] | None) -> list[str]:
        return [str(v).strip() for v in (values or []) if str(v or '').strip()]

    def _ci_in(col: Any, values: list[str]) -> ColumnElement[bool]:
        vals = [str(v).strip().lower() for v in values if str(v).strip()]
        if not vals:
            return true()
        return func.lower(func.trim(func.coalesce(col, ''))).in_(vals)

    def _ci_contains_any(col: Any, values: list[str]) -> ColumnElement[bool]:
        _esc2 = str.maketrans({'%': '\\%', '_': '\\_', '\\': '\\\\'})
        vals = [str(v).strip().lower().translate(_esc2) for v in values if str(v).strip()]
        if not vals:
            return true()
        lc = func.lower(func.coalesce(col, ''))
        return or_(*[lc.like(f'%{v}%', escape='\\') for v in vals])

    lib_ids = _norm_ids(library_ids)
    if library_id and str(library_id).strip():
        lib_ids = [str(library_id).strip()]
    if lib_ids:
        stmt = stmt.where(Paper.library_id.in_(lib_ids))

    if user_id is not None:
        allowed = _accessible_library_ids_subquery(user_id=int(user_id))
        stmt = stmt.where(Paper.library_id.in_(allowed))

    if ft:
        stmt = stmt.where(Paper.file_type == ft)

    if bool(f.has_doi) and bool(f.has_isbn):
        stmt = stmt.where(_has_text(Paper.doi) | _has_text(Paper.isbn))
    elif bool(f.has_doi):
        stmt = stmt.where(_has_text(Paper.doi))
    elif bool(f.has_isbn):
        stmt = stmt.where(_has_text(Paper.isbn))

    if bool(f.missing_id):
        stmt = stmt.where(~_has_text(Paper.doi) & ~_has_text(Paper.isbn))

    if bool(f.completed_only):
        stmt = stmt.where(Paper.is_completed.is_(True))

    tag_names = _norm_list(f.tag_names)
    if tag_names:
        tag_lc = [t.lower() for t in tag_names]
        tag_match = exists(
            select(1)
            .select_from(PaperTag)
            .join(Tag, Tag.id == PaperTag.tag_id)
            .where(PaperTag.paper_id == Paper.id)
            .where(func.lower(func.coalesce(Tag.name, '')).in_(tag_lc))
        )
        stmt = stmt.where(tag_match)

    marker_ids = _norm_list(f.marker_ids)
    if marker_ids:
        marker_match = exists(
            select(1)
            .select_from(PaperMarker)
            .where(PaperMarker.paper_id == Paper.id)
            .where(PaperMarker.marker_id.in_(marker_ids))
        )
        stmt = stmt.where(marker_match)

    year_min = f.year_min
    year_max = f.year_max
    if year_min is not None and year_max is not None and int(year_min) > int(year_max):
        year_min, year_max = year_max, year_min
    if year_min is not None or year_max is not None:
        year_trim = func.trim(func.coalesce(Paper.published_year, ''))
        year_int = func.cast(year_trim, Integer)
        stmt = stmt.where(func.length(year_trim) == 4)
        if year_min is not None:
            stmt = stmt.where(year_int >= int(year_min))
        if year_max is not None:
            stmt = stmt.where(year_int <= int(year_max))

    authors = _norm_list(f.authors)
    if authors:
        stmt = stmt.where(_ci_contains_any(Paper.authors, authors))

    journals = _norm_list(f.journals)
    if journals:
        stmt = stmt.where(_ci_in(Paper.journal, journals))

    publishers = _norm_list(f.publishers)
    if publishers:
        stmt = stmt.where(_ci_in(Paper.publisher, publishers))

    series = _norm_list(f.series)
    if series:
        stmt = stmt.where(_ci_in(Paper.series, series))

    languages = _norm_list(f.languages)
    if languages:
        stmt = stmt.where(_ci_in(Paper.language, languages))

    genres = _norm_list(f.genres)
    if genres:
        stmt = stmt.where(_ci_contains_any(Paper.genres, genres))

    if user_id is not None and bool(f.favorites_only):
        fav_match = exists(
            select(1)
            .select_from(PaperFavorite)
            .where(PaperFavorite.paper_id == Paper.id)
            .where(PaperFavorite.user_id == int(user_id))
        )
        stmt = stmt.where(fav_match)

    if user_id is not None and bool(f.to_read_only):
        to_read_match = exists(
            select(1)
            .select_from(PaperToRead)
            .where(PaperToRead.paper_id == Paper.id)
            .where(PaperToRead.user_id == int(user_id))
        )
        stmt = stmt.where(to_read_match)

    if q:
        stmt = stmt.where(_search_scope_clause(query=q, mode=mode))

    return stmt


def count_papers_filtered(
    *,
    user_id: int | None = None,
    library_id: str | None = None,
    library_ids: list[str] | None = None,
    query: str | None = None,
    mode: str = 'all',
    filters: PaperFilters | None = None,
) -> int:
    """Return the total count of papers matching the given filters.

    Uses the same filter logic as :func:`list_papers_filtered` but runs a
    ``SELECT COUNT(*)`` instead of fetching rows.
    """
    base = select(Paper.id).where(_NOT_DELETED)
    filtered = _apply_paper_filters(
        base,
        user_id=user_id,
        library_id=library_id,
        library_ids=library_ids,
        query=query,
        mode=mode,
        filters=filters,
    )
    with get_session() as session:
        return session.execute(
            select(func.count()).select_from(filtered.subquery())
        ).scalar_one()


def list_papers_filtered(
    *,
    user_id: int | None = None,
    library_id: str | None = None,
    library_ids: list[str] | None = None,
    query: str | None = None,
    mode: str = 'all',
    filters: PaperFilters | None = None,
    sort: str = 'default',
    limit: int | None = 500,
    offset: int = 0,
) -> list[PaperItem]:
    """List/search papers with a small set of DB-backed filters.

    - If `query` is provided, applies the same semantics as `search_papers`.
    - Filters are applied in SQL so pagination/limits remain correct.
    """

    with get_session() as session:
        stmt = _apply_paper_filters(
            select(Paper).where(_NOT_DELETED),
            user_id=user_id,
            library_id=library_id,
            library_ids=library_ids,
            query=query,
            mode=mode,
            filters=filters,
        )

        # Note: we rely on EXISTS subqueries for tag/marker/favorite filters,
        # avoiding duplicate rows from joins.

        # Sort
        sort_key = str(sort or 'default').strip().lower() or 'default'
        if sort_key == 'recent':
            stmt = stmt.order_by(Paper.created_at.desc())
        elif sort_key == 'title_asc':
            stmt = stmt.order_by(Paper.title.asc(), Paper.created_at.desc())
        elif sort_key == 'title_desc':
            stmt = stmt.order_by(Paper.title.desc(), Paper.created_at.desc())
        elif sort_key in {'author_asc', 'authors_asc'}:
            stmt = stmt.order_by(func.lower(func.coalesce(Paper.authors, '')).asc(), Paper.created_at.desc())
        elif sort_key == 'year_desc':
            year_trim = func.trim(func.coalesce(Paper.published_year, ''))
            year_val = case((func.length(year_trim) == 4, func.cast(year_trim, Integer)), else_=None)
            stmt = stmt.order_by(year_val.desc(), Paper.created_at.desc())
        elif sort_key == 'year_asc':
            year_trim = func.trim(func.coalesce(Paper.published_year, ''))
            year_val = case((func.length(year_trim) == 4, func.cast(year_trim, Integer)), else_=None)
            stmt = stmt.order_by(year_val.asc(), Paper.created_at.desc())
        elif sort_key == 'last_opened':
            stmt = stmt.order_by(Paper.last_opened_at.desc(), Paper.created_at.desc())
        elif sort_key == 'last_read':
            stmt = stmt.order_by(Paper.last_read_at.desc(), Paper.created_at.desc())
        else:
            # Default sorting is configurable via Admin → Library.
            try:
                from papervisor.services.settings import get_default_sort

                default_sort = str(get_default_sort() or 'recent').strip().lower()
            except Exception:
                default_sort = 'recent'

            if default_sort == 'title_asc':
                stmt = stmt.order_by(Paper.title.asc(), Paper.created_at.desc())
            elif default_sort == 'title_desc':
                stmt = stmt.order_by(Paper.title.desc(), Paper.created_at.desc())
            else:
                stmt = stmt.order_by(Paper.created_at.desc())

        if offset and offset > 0:
            stmt = stmt.offset(int(offset))

        if limit is not None and limit > 0:
            stmt = stmt.limit(int(limit))

        rows = session.execute(stmt).scalars().all()

        fav_ids: set[str] = set()
        to_read_ids: set[str] = set()
        if user_id is not None and rows:
            ids = [str(r.id) for r in rows]
            fav_ids = _favorite_ids_for(session=session, user_id=int(user_id), paper_ids=ids)
            to_read_ids = _to_read_ids_for(session=session, user_id=int(user_id), paper_ids=ids)

        return [
            PaperItem(
                id=r.id,
                title=r.title,
                subtitle=r.subtitle or '',
                reading_progress=float(r.reading_progress or 0.0),
                is_completed=bool(r.is_completed),
                is_favorite=(str(r.id) in fav_ids) if user_id is not None else False,
                is_to_read=(str(r.id) in to_read_ids) if user_id is not None else False,
                open_count_total=int(r.open_count_total or 0),
                open_count_since_reset=int(r.open_count_since_reset or 0),
                file_suffix=Path(str(r.file_path or '')).suffix if r.file_path else '',
                file_type=str(r.file_type or "paper"),
            )
            for r in rows
        ]


def list_books(*, library_id: str | None = None) -> list[PaperItem]:
    with get_session() as session:
        stmt = select(Paper).where(_NOT_DELETED).where(Paper.file_type == 'book').order_by(Paper.title.asc(), Paper.created_at.desc())
        if library_id:
            stmt = stmt.where(Paper.library_id == library_id)
        rows = session.execute(stmt).scalars().all()
        return [
            PaperItem(
                id=r.id,
                title=r.title,
                subtitle=r.subtitle or '',
                reading_progress=float(r.reading_progress or 0.0),
                is_completed=bool(r.is_completed),
                is_favorite=False,
                open_count_total=int(r.open_count_total or 0),
                open_count_since_reset=int(r.open_count_since_reset or 0),
                file_suffix=Path(str(r.file_path or '')).suffix if r.file_path else '',
                file_type=str(r.file_type or "paper"),
            )
            for r in rows
        ]


def get_dashboard_counts(*, user_id: int | None = None, library_id: str | None = None) -> dict[str, int]:
    with get_session() as session:
        base = select(Paper.id).select_from(Paper)
        if library_id:
            base = base.where(Paper.library_id == library_id)

        if user_id is not None:
            allowed = _accessible_library_ids_subquery(user_id=int(user_id))
            base = base.where(Paper.library_id.in_(allowed))

        total = session.execute(select(func.count()).select_from(base.subquery())).scalar_one()

        completed = session.execute(
            select(func.count()).select_from(
                base.where(Paper.is_completed.is_(True)).subquery()
            )
        ).scalar_one()

        if user_id is None:
            favorites = 0
            to_read = 0
        else:
            uid = int(user_id)
            fav_match = exists(
                select(1)
                .select_from(PaperFavorite)
                .where(PaperFavorite.user_id == uid)
                .where(PaperFavorite.paper_id == Paper.id)
            )
            to_read_match = exists(
                select(1)
                .select_from(PaperToRead)
                .where(PaperToRead.user_id == uid)
                .where(PaperToRead.paper_id == Paper.id)
            )

            favorites = session.execute(
                select(func.count()).select_from(base.where(fav_match).subquery())
            ).scalar_one()
            to_read = session.execute(
                select(func.count()).select_from(base.where(to_read_match).subquery())
            ).scalar_one()

    return {'total': int(total), 'favorites': int(favorites), 'to_read': int(to_read), 'completed': int(completed)}


def list_favorite_papers(*, user_id: int | None = None, library_id: str | None = None, limit: int = 50) -> list[PaperItem]:
    if user_id is None:
        return []

    with get_session() as session:
        stmt = (
            select(Paper).where(_NOT_DELETED)
            .join(PaperFavorite, PaperFavorite.paper_id == Paper.id)
            .where(PaperFavorite.user_id == int(user_id))
            .order_by(PaperFavorite.created_at.desc(), Paper.created_at.desc())
        )
        if library_id:
            stmt = stmt.where(Paper.library_id == library_id)
        allowed = _accessible_library_ids_subquery(user_id=int(user_id))
        stmt = stmt.where(Paper.library_id.in_(allowed))
        rows = session.execute(stmt.limit(int(limit))).scalars().all()
        fav_ids = {str(r.id) for r in rows}
        to_read_ids: set[str] = set()
        if rows:
            to_read_ids = _to_read_ids_for(session=session, user_id=int(user_id), paper_ids=[str(r.id) for r in rows])

    return [
        PaperItem(
            id=r.id,
            title=r.title,
            subtitle=r.subtitle or '',
            reading_progress=float(r.reading_progress or 0.0),
            is_completed=bool(r.is_completed),
            is_favorite=str(r.id) in fav_ids,
            is_to_read=str(r.id) in to_read_ids,
            open_count_total=int(r.open_count_total or 0),
            open_count_since_reset=int(r.open_count_since_reset or 0),
            file_suffix=Path(str(r.file_path or '')).suffix if r.file_path else '',
                file_type=str(r.file_type or "paper"),
        )
        for r in rows
    ]


def list_to_read_papers(*, user_id: int | None = None, library_id: str | None = None, limit: int = 50) -> list[PaperItem]:
    if user_id is None:
        return []

    with get_session() as session:
        stmt = (
            select(Paper).where(_NOT_DELETED)
            .join(PaperToRead, PaperToRead.paper_id == Paper.id)
            .where(PaperToRead.user_id == int(user_id))
            .order_by(PaperToRead.created_at.desc(), Paper.created_at.desc())
        )
        if library_id:
            stmt = stmt.where(Paper.library_id == library_id)
        allowed = _accessible_library_ids_subquery(user_id=int(user_id))
        stmt = stmt.where(Paper.library_id.in_(allowed))
        rows = session.execute(stmt.limit(int(limit))).scalars().all()

        fav_ids: set[str] = set()
        if rows:
            fav_ids = _favorite_ids_for(session=session, user_id=int(user_id), paper_ids=[str(r.id) for r in rows])

    return [
        PaperItem(
            id=r.id,
            title=r.title,
            subtitle=r.subtitle or '',
            reading_progress=float(r.reading_progress or 0.0),
            is_completed=bool(r.is_completed),
            is_favorite=str(r.id) in fav_ids,
            is_to_read=True,
            open_count_total=int(r.open_count_total or 0),
            open_count_since_reset=int(r.open_count_since_reset or 0),
            file_suffix=Path(str(r.file_path or '')).suffix if r.file_path else '',
                file_type=str(r.file_type or "paper"),
        )
        for r in rows
    ]


def list_continue_reading(*, user_id: int | None = None, library_id: str | None = None, limit: int = 24) -> list[PaperItem]:
    with get_session() as session:
        stmt = (
            select(Paper).where(_NOT_DELETED)
            .where(Paper.is_completed.is_(False))
            .where(Paper.reading_progress > 0)
            .order_by(
                Paper.last_read_at.desc().nullslast(),
                Paper.last_opened_at.desc().nullslast(),
                Paper.created_at.desc(),
            )
        )
        if library_id:
            stmt = stmt.where(Paper.library_id == library_id)

        if user_id is not None:
            allowed = _accessible_library_ids_subquery(user_id=int(user_id))
            stmt = stmt.where(Paper.library_id.in_(allowed))
        rows = session.execute(stmt.limit(int(limit))).scalars().all()

        fav_ids: set[str] = set()
        to_read_ids: set[str] = set()
        if user_id is not None and rows:
            ids = [str(r.id) for r in rows]
            fav_ids = _favorite_ids_for(session=session, user_id=int(user_id), paper_ids=ids)
            to_read_ids = _to_read_ids_for(session=session, user_id=int(user_id), paper_ids=ids)

    return [
        PaperItem(
            id=r.id,
            title=r.title,
            subtitle=r.subtitle or '',
            reading_progress=float(r.reading_progress or 0.0),
            is_completed=bool(r.is_completed),
            is_favorite=(str(r.id) in fav_ids) if user_id is not None else False,
            is_to_read=(str(r.id) in to_read_ids) if user_id is not None else False,
            open_count_total=int(r.open_count_total or 0),
            open_count_since_reset=int(r.open_count_since_reset or 0),
            file_suffix=Path(str(r.file_path or '')).suffix if r.file_path else '',
                file_type=str(r.file_type or "paper"),
        )
        for r in rows
    ]


def list_most_opened(*, user_id: int | None = None, library_id: str | None = None, limit: int = 20) -> list[PaperItem]:
    with get_session() as session:
        stmt = select(Paper).where(_NOT_DELETED).order_by(
            Paper.open_count_since_reset.desc(),
            Paper.open_count_total.desc(),
            Paper.created_at.desc(),
        )
        if library_id:
            stmt = stmt.where(Paper.library_id == library_id)

        if user_id is not None:
            allowed = _accessible_library_ids_subquery(user_id=int(user_id))
            stmt = stmt.where(Paper.library_id.in_(allowed))
        rows = session.execute(stmt.limit(int(limit))).scalars().all()

        fav_ids: set[str] = set()
        to_read_ids: set[str] = set()
        if user_id is not None and rows:
            ids = [str(r.id) for r in rows]
            fav_ids = _favorite_ids_for(session=session, user_id=int(user_id), paper_ids=ids)
            to_read_ids = _to_read_ids_for(session=session, user_id=int(user_id), paper_ids=ids)

    return [
        PaperItem(
            id=r.id,
            title=r.title,
            subtitle=r.subtitle or '',
            reading_progress=float(r.reading_progress or 0.0),
            is_completed=bool(r.is_completed),
            is_favorite=(str(r.id) in fav_ids) if user_id is not None else False,
            is_to_read=(str(r.id) in to_read_ids) if user_id is not None else False,
            open_count_total=int(r.open_count_total or 0),
            open_count_since_reset=int(r.open_count_since_reset or 0),
            file_suffix=Path(str(r.file_path or '')).suffix if r.file_path else '',
                file_type=str(r.file_type or "paper"),
        )
        for r in rows
    ]
