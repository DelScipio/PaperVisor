from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Integer, and_, case, delete, exists, false, func, or_, select, true
from sqlalchemy.sql import Select

from papervisor.db.models import (
    Library,
    LibraryShare,
    Marker,
    Paper,
    PaperFavorite,
    PaperMarker,
    PaperTag,
    PaperToRead,
    Tag,
)
from sqlalchemy.orm import Session

from papervisor.db.session import get_session, use_session

_NOT_DELETED = Paper.deleted_at.is_(None)
from papervisor.domain import PaperItem, MarkerItem
from papervisor.services.papers_search import PaperFilters
from papervisor.services.sharing import require_library_read


def list_marker_papers_filtered(
    *,
    user_id: int | None = None,
    marker_id: str,
    library_ids: list[str] | None = None,
    filters: PaperFilters | None = None,
    sort: str = 'default',
    limit: int = 500,
) -> list[PaperItem]:
    """List marker papers, applying the same UI filters as the main listing.

    This is used to make sidebar-selected markers (manual + smart) compatible with
    the Filters drawer (file type, tags, year range, etc.).
    """

    marker_id = str(marker_id or '').strip()
    if not marker_id:
        return []

    # `filters` is typically a `PaperFilters` instance coming from the UI.
    # Keep it permissive (object) to avoid forcing callers, but default to an
    # empty `PaperFilters` for consistent behavior.
    f = filters if filters is not None else PaperFilters()

    def _has_text(col: Any) -> Any:
        return func.length(func.trim(func.coalesce(col, ''))) > 0

    def _norm_list(values: list[str] | None) -> list[str]:
        if not values:
            return []
        out: list[str] = []
        for v in values:
            v = str(v or '').strip()
            if v:
                out.append(v)
        return out

    def _ci_in(col: Any, values: list[str]) -> Any:
        vals = [str(v).strip().lower() for v in values if str(v).strip()]
        if not vals:
            return True
        return func.lower(func.trim(func.coalesce(col, ''))).in_(vals)

    def _ci_contains_any(col: Any, values: list[str]) -> Any:
        vals = [str(v).strip().lower() for v in values if str(v).strip()]
        if not vals:
            return True
        lc = func.lower(func.coalesce(col, ''))
        return or_(*[lc.like(f'%{v}%') for v in vals])

    def _apply_ui_filters(stmt: Select[tuple[Paper]]) -> Select[tuple[Paper]]:
        if f is None:
            return stmt

        # File type
        ft = str(getattr(f, 'file_type', None) or '').strip().lower() or None
        if ft in {'paper', 'book'}:
            stmt = stmt.where(Paper.file_type == ft)

        if bool(getattr(f, 'has_doi', False)):
            stmt = stmt.where(_has_text(Paper.doi))
        if bool(getattr(f, 'has_isbn', False)):
            stmt = stmt.where(_has_text(Paper.isbn))
        if bool(getattr(f, 'completed_only', False)):
            stmt = stmt.where(Paper.is_completed.is_(True))

        tag_names = _norm_list(getattr(f, 'tag_names', None))
        no_tags = bool(getattr(f, 'no_tags', False))
        if no_tags:
            stmt = stmt.where(
                ~exists(
                    select(1)
                    .select_from(PaperTag)
                    .where(PaperTag.paper_id == Paper.id)
                )
            )
            tag_names = []
        elif tag_names:
            tag_lc = [t.lower() for t in tag_names]
            stmt = (
                stmt.join(PaperTag, PaperTag.paper_id == Paper.id)
                .join(Tag, Tag.id == PaperTag.tag_id)
                .where(func.lower(func.coalesce(Tag.name, '')).in_(tag_lc))
            )

        marker_ids = _norm_list(getattr(f, 'marker_ids', None))
        no_markers = bool(getattr(f, 'no_markers', False))
        if no_markers:
            stmt = stmt.where(
                ~exists(
                    select(1)
                    .select_from(PaperMarker)
                    .where(PaperMarker.paper_id == Paper.id)
                )
            )
            marker_ids = []
        elif marker_ids:
            stmt = stmt.join(PaperMarker, PaperMarker.paper_id == Paper.id).where(PaperMarker.marker_id.in_(marker_ids))

        year_min = getattr(f, 'year_min', None)
        year_max = getattr(f, 'year_max', None)
        if year_min is not None or year_max is not None:
            year_trim = func.trim(func.coalesce(Paper.published_year, ''))
            year_int = func.cast(year_trim, Integer)
            stmt = stmt.where(func.length(year_trim) == 4)
            if year_min is not None:
                stmt = stmt.where(year_int >= int(year_min))
            if year_max is not None:
                stmt = stmt.where(year_int <= int(year_max))

        authors = _norm_list(getattr(f, 'authors', None))
        if authors:
            stmt = stmt.where(_ci_contains_any(Paper.authors, authors))

        journals = _norm_list(getattr(f, 'journals', None))
        if journals:
            stmt = stmt.where(_ci_in(Paper.journal, journals))

        publishers = _norm_list(getattr(f, 'publishers', None))
        if publishers:
            stmt = stmt.where(_ci_in(Paper.publisher, publishers))

        series = _norm_list(getattr(f, 'series', None))
        if series:
            stmt = stmt.where(_ci_in(Paper.series, series))

        languages = _norm_list(getattr(f, 'languages', None))
        if languages:
            stmt = stmt.where(_ci_in(Paper.language, languages))

        genres = _norm_list(getattr(f, 'genres', None))
        if genres:
            stmt = stmt.where(_ci_contains_any(Paper.genres, genres))

        if user_id is not None and bool(getattr(f, 'favorites_only', False)):
            stmt = stmt.join(PaperFavorite, PaperFavorite.paper_id == Paper.id).where(PaperFavorite.user_id == int(user_id))

        if user_id is not None and bool(getattr(f, 'to_read_only', False)):
            stmt = stmt.join(PaperToRead, PaperToRead.paper_id == Paper.id).where(PaperToRead.user_id == int(user_id))

        # Avoid duplicates from joins.
        if (
            tag_names
            or marker_ids
            or no_tags
            or no_markers
            or authors
            or journals
            or publishers
            or series
            or languages
            or genres
            or bool(getattr(f, 'favorites_only', False))
            or bool(getattr(f, 'to_read_only', False))
        ):
            stmt = stmt.distinct()

        return stmt

    def _norm_ids(values: list[str] | None) -> list[str]:
        out: list[str] = []
        for v in values or []:
            s = str(v or '').strip()
            if s:
                out.append(s)
        return out

    lib_ids = _norm_ids(library_ids)

    with get_session() as session:
        marker = session.get(Marker, marker_id)
        if marker is None:
            return []

        # In "marker view", the selected marker is the primary constraint.
        # If the UI's drawer marker filter includes this same id, it can cause either:
        # - redundant joins (manual markers), or
        # - empty results (smart markers aren't in PaperMarker).
        if isinstance(f, PaperFilters):
            from dataclasses import replace

            cur_marker_ids = _norm_list(getattr(f, 'marker_ids', None))
            if cur_marker_ids:
                if bool(marker.is_smart):
                    cleaned = [mid for mid in cur_marker_ids if str(mid) != marker_id]
                    if cleaned != cur_marker_ids:
                        f = replace(f, marker_ids=cleaned)
                else:
                    # Manual marker view already constrains to this marker.
                    f = replace(f, marker_ids=None)

        if bool(marker.is_smart):
            query = _parse_smart_query_v2(marker.rules_json or '')
            stmt = select(Paper).where(_NOT_DELETED)
            stmt = _apply_smart_marker_filters(stmt, marker=marker, query=query, user_id=user_id)
        else:
            stmt = select(Paper).where(_NOT_DELETED).join(PaperMarker, PaperMarker.paper_id == Paper.id).where(PaperMarker.marker_id == marker_id)
            if user_id is not None:
                stmt = stmt.where(Paper.library_id.in_(_allowed_library_ids_subquery(user_id=int(user_id))))

        if lib_ids:
            stmt = stmt.where(Paper.library_id.in_(lib_ids))

        stmt = _apply_ui_filters(stmt)

        # Sort (mirrors list_papers_filtered)
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

        stmt = stmt.limit(int(limit))
        rows = session.execute(stmt).scalars().all()

        if user_id is None or not rows:
            return [_paper_item_from_row(r) for r in rows]

        fav_ids = {
            str(x)
            for x in session.execute(
                select(PaperFavorite.paper_id)
                .where(PaperFavorite.user_id == int(user_id))
                .where(PaperFavorite.paper_id.in_([str(r.id) for r in rows]))
            ).scalars().all()
        }

        to_read_ids = {
            str(x)
            for x in session.execute(
                select(PaperToRead.paper_id)
                .where(PaperToRead.user_id == int(user_id))
                .where(PaperToRead.paper_id.in_([str(r.id) for r in rows]))
            ).scalars().all()
        }

        return [
            _paper_item_from_row(
                r,
                is_favorite=(str(r.id) in fav_ids),
                is_to_read=(str(r.id) in to_read_ids),
            )
            for r in rows
        ]


def _parse_smart_query_v2(raw: str | None) -> dict[str, object] | None:
    """Parse v2 smart-marker rule tree.

    Schema (v2):
      {"version": 2, "root": {"type": "group", "op": "and"|"or", "children": [node...]}}
    node:
      group: {"type":"group","op":"and"|"or","children":[...]}
      rule:  {"type":"rule","field":...,"operator":...,"value":...}
    """

    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if int(data.get('version') or 0) != 2:
        return None
    root = data.get('root')
    if not isinstance(root, dict):
        return None
    if str(root.get('type') or '') != 'group':
        return None
    return cast(dict[str, object], data)


def _smart_query_is_effectively_empty(query: dict[str, Any] | None) -> bool:
    if not query:
        return True
    root = query.get('root')
    if not isinstance(root, dict):
        return True
    children = root.get('children')
    return not (isinstance(children, list) and len(children) > 0)


def _normalize_list(values: list[str] | None) -> list[str]:
    from papervisor.core.sanitizers import normalize_list as _nl
    return _nl(values)


def list_markers(user_id: int | None = None) -> list[MarkerItem]:
    with get_session() as session:
        stmt = select(Marker).order_by(Marker.name.asc())
        if user_id is not None:
            stmt = stmt.where(or_(Marker.owner_user_id == user_id, Marker.visibility == 'global'))
        
        markers = session.execute(stmt).scalars().all()

        # Count manual assignments for badges.
        manual_count_stmt = (
            select(PaperMarker.marker_id, func.count(func.distinct(PaperMarker.paper_id)))
            .join(Paper, Paper.id == PaperMarker.paper_id)
            .group_by(PaperMarker.marker_id)
        )
        if user_id is not None:
            manual_count_stmt = manual_count_stmt.where(Paper.library_id.in_(_allowed_library_ids_subquery(user_id=int(user_id))))
        count_rows = session.execute(manual_count_stmt).all()
        manual_counts: dict[str, int] = {str(sid): int(cnt or 0) for (sid, cnt) in count_rows}

        # Count smart markers by evaluating their rules.
        smart_counts: dict[str, int] = {}
        for s in markers:
            if not bool(s.is_smart):
                continue
            query = _parse_smart_query_v2(s.rules_json or '')
            if _smart_query_is_effectively_empty(query):
                smart_counts[str(s.id)] = 0
                continue
            c_stmt = select(func.count(func.distinct(Paper.id)))
            c_stmt = _apply_smart_marker_filters(c_stmt, marker=s, query=query, user_id=user_id)
            smart_counts[str(s.id)] = int(session.execute(c_stmt).scalar_one() or 0)

    return [
        MarkerItem(
            id=str(s.id),
            name=s.name,
            icon=s.icon or 'category',
            is_smart=bool(s.is_smart),
            scope=str(s.scope or 'all'),
            paper_count=(
                int(smart_counts.get(str(s.id), 0) or 0)
                if bool(s.is_smart)
                else int(manual_counts.get(str(s.id), 0) or 0)
            ),
            owner_user_id=s.owner_user_id,
            visibility=s.visibility,
            is_owned_by_me=bool(s.owner_user_id == user_id) if user_id else False,
        )
        for s in markers
    ]


def get_marker(*, marker_id: str, user_id: int | None = None) -> tuple[MarkerItem, dict[str, Any] | None]:
    marker_id = str(marker_id or '').strip()
    if not marker_id:
        raise ValueError('Marker id is required')

    with get_session() as session:
        row = session.get(Marker, marker_id)
        if row is None:
            raise ValueError('Marker not found')
        
        # Check access
        if user_id is not None:
            if row.visibility == 'private' and row.owner_user_id != user_id:
                raise ValueError('Access denied')

        if bool(row.is_smart):
            query = _parse_smart_query_v2(row.rules_json or '')
            if _smart_query_is_effectively_empty(query):
                count = 0
            else:
                c_stmt = select(func.count(func.distinct(Paper.id)))
                c_stmt = _apply_smart_marker_filters(c_stmt, marker=row, query=query, user_id=user_id)
                count = session.execute(c_stmt).scalar_one()
        else:
            c_stmt = (
                select(func.count(func.distinct(PaperMarker.paper_id)))
                .join(Paper, Paper.id == PaperMarker.paper_id)
                .where(PaperMarker.marker_id == marker_id)
            )
            if user_id is not None:
                c_stmt = c_stmt.where(Paper.library_id.in_(_allowed_library_ids_subquery(user_id=int(user_id))))
            count = session.execute(c_stmt).scalar_one()

    item = MarkerItem(
        id=str(row.id),
        name=row.name,
        icon=row.icon or 'category',
        is_smart=bool(row.is_smart),
        scope=str(row.scope or 'all'),
        paper_count=int(count or 0),
        owner_user_id=row.owner_user_id,
        visibility=row.visibility,
        is_owned_by_me=bool(row.owner_user_id == user_id) if user_id else False,
    )
    query = _parse_smart_query_v2(row.rules_json or '')
    return item, query


def create_marker(
    *,
    name: str,
    icon: str = 'category',
    is_smart: bool = False,
    rules_json: str | None = None,
    visibility: str = 'private',
    owner_user_id: int | None = None,
) -> MarkerItem:
    name = str(name or '').strip()
    if not name:
        raise ValueError('Marker name is required')
    normalized_name = name.lower()

    marker_id = str(uuid.uuid4())
    visibility = str(visibility or 'private').strip().lower() or 'private'
    if visibility not in {'private', 'global'}:
        visibility = 'private'

    if bool(is_smart):
        rules_json = str(rules_json or '')
    else:
        rules_json = ''

    with get_session() as session:
        # Check for existing marker with same name (case-insensitive) for this owner.
        stmt = select(Marker).where(func.lower(Marker.name) == normalized_name)
        if owner_user_id is not None:
            stmt = stmt.where(Marker.owner_user_id == owner_user_id)
        else:
            stmt = stmt.where(Marker.owner_user_id.is_(None))
        
        existing = session.execute(stmt).scalar_one_or_none()
        if existing is not None:
            raise ValueError('A marker with this name already exists')

        row = Marker(
            id=marker_id,
            name=name,
            icon=str(icon or 'category'),
            is_smart=bool(is_smart),
            scope='all',
            rules_json=str(rules_json or ''),
            owner_user_id=owner_user_id,
            visibility=visibility,
        )
        session.add(row)
        session.commit()

    return MarkerItem(
        id=row.id,
        name=row.name,
        icon=row.icon or 'category',
        is_smart=bool(row.is_smart),
        scope=str(row.scope or 'all'),
        paper_count=0,
        owner_user_id=row.owner_user_id,
        visibility=row.visibility,
        is_owned_by_me=True if owner_user_id else False,
    )


def update_marker(
    *,
    marker_id: str,
    name: str,
    icon: str,
    is_smart: bool,
    rules_json: str | None = None,
    visibility: str | None = None,
    user_id: int | None = None,
) -> MarkerItem:
    marker_id = str(marker_id or '').strip()
    if not marker_id:
        raise ValueError('Marker id is required')

    name = str(name or '').strip()
    if not name:
        raise ValueError('Marker name is required')
    normalized_name = name.lower()

    if bool(is_smart):
        rules_json = str(rules_json or '')
    else:
        rules_json = ''

    with get_session() as session:
        row = session.get(Marker, marker_id)
        if row is None:
            raise ValueError('Marker not found')
        
        if user_id is not None and row.owner_user_id != user_id:
            raise ValueError('Access denied')

        if visibility is not None:
            v = str(visibility or '').strip().lower()
            if v in {'private', 'global'}:
                row.visibility = v

        # Check for name collision (case-insensitive), scoped to owner.
        stmt = select(Marker).where(func.lower(Marker.name) == normalized_name).where(Marker.id != marker_id)
        if row.owner_user_id is not None:
            stmt = stmt.where(Marker.owner_user_id == row.owner_user_id)
        else:
            stmt = stmt.where(Marker.owner_user_id.is_(None))
            
        existing = session.execute(stmt).scalar_one_or_none()
        if existing is not None:
            raise ValueError('A marker with this name already exists')

        row.name = name
        row.icon = str(icon or 'category')
        row.is_smart = bool(is_smart)
        row.scope = 'all'
        row.rules_json = str(rules_json or '') if bool(is_smart) else ''
        session.commit()

        if bool(row.is_smart):
            query_live = _parse_smart_query_v2(row.rules_json or '')
            if _smart_query_is_effectively_empty(query_live):
                count = 0
            else:
                c_stmt = select(func.count(func.distinct(Paper.id)))
                c_stmt = _apply_smart_marker_filters(c_stmt, marker=row, query=query_live, user_id=user_id)
                count = session.execute(c_stmt).scalar_one()
        else:
            c_stmt = (
                select(func.count(func.distinct(PaperMarker.paper_id)))
                .join(Paper, Paper.id == PaperMarker.paper_id)
                .where(PaperMarker.marker_id == marker_id)
            )
            if user_id is not None:
                c_stmt = c_stmt.where(Paper.library_id.in_(_allowed_library_ids_subquery(user_id=int(user_id))))
            count = session.execute(c_stmt).scalar_one()

    return MarkerItem(
        id=row.id,
        name=row.name,
        icon=row.icon or 'category',
        is_smart=bool(row.is_smart),
        scope=str(row.scope or 'all'),
        paper_count=int(count or 0),
        owner_user_id=row.owner_user_id,
        visibility=row.visibility,
        is_owned_by_me=bool(row.owner_user_id == user_id) if user_id else False,
    )


def delete_marker(*, marker_id: str, user_id: int | None = None) -> None:
    marker_id = str(marker_id or '').strip()
    if not marker_id:
        raise ValueError('Marker id is required')

    with get_session() as session:
        row = session.get(Marker, marker_id)
        if row is None:
            return
        
        if user_id is not None and row.owner_user_id != user_id:
            raise ValueError('Access denied')

        session.delete(row)
        session.commit()


def set_paper_markers(*, paper_id: str, marker_ids: list[str], user_id: int | None = None) -> None:
    paper_id = str(paper_id or '').strip()
    if not paper_id:
        raise ValueError('paper_id is required')

    marker_ids = [str(s).strip() for s in marker_ids if str(s).strip()]

    with get_session() as session:
        paper = session.get(Paper, paper_id)
        if paper is None:
            raise ValueError('Paper not found')

        # If user context is provided, ensure the user can read this paper's library.
        if user_id is not None:
            lib_id = str(paper.library_id or '').strip()
            if not lib_id:
                raise ValueError('Library is required')
            require_library_read(user_id=int(user_id), library_id=lib_id)

        # Only allow manual shelves here.
        if user_id is not None:
            # Allow modifying shelves the user owns, plus global shelves.
            editable = set(
                session.execute(
                    select(Marker.id)
                    .where(Marker.is_smart.is_(False))
                    .where(or_(Marker.owner_user_id == int(user_id), Marker.visibility == 'global'))
                ).scalars().all()
            )

            allowed = set(
                session.execute(
                    select(Marker.id)
                    .where(Marker.is_smart.is_(False))
                    .where(Marker.id.in_(marker_ids))
                    .where(or_(Marker.owner_user_id == int(user_id), Marker.visibility == 'global'))
                ).scalars().all()
            )

            session.execute(
                delete(PaperMarker)
                .where(PaperMarker.paper_id == paper_id)
                .where(PaperMarker.marker_id.in_(editable))
            )
            for sid in allowed:
                session.add(PaperMarker(paper_id=paper_id, marker_id=sid))
        else:
            allowed = set(
                session.execute(select(Marker.id).where(Marker.is_smart.is_(False)).where(Marker.id.in_(marker_ids))).scalars().all()
            )
            session.execute(delete(PaperMarker).where(PaperMarker.paper_id == paper_id))
            for sid in allowed:
                session.add(PaperMarker(paper_id=paper_id, marker_id=sid))
        session.commit()


def list_paper_markers(*, paper_id: str) -> list[str]:
    paper_id = str(paper_id or '').strip()
    if not paper_id:
        return []

    with get_session() as session:
        rows = session.execute(select(PaperMarker.marker_id).where(PaperMarker.paper_id == paper_id)).scalars().all()
    return [str(r) for r in rows]


def _paper_item_from_row(r: Paper, *, is_favorite: bool | None = None, is_to_read: bool | None = None) -> PaperItem:
    return PaperItem(
        id=r.id,
        title=r.title,
        subtitle=r.subtitle or '',
        reading_progress=float(r.reading_progress or 0.0),
        is_completed=bool(r.is_completed),
        is_favorite=False if is_favorite is None else bool(is_favorite),
        is_to_read=False if is_to_read is None else bool(is_to_read),
        open_count_total=int(r.open_count_total or 0),
        open_count_since_reset=int(r.open_count_since_reset or 0),
        file_suffix=Path(str(r.file_path or '')).suffix if r.file_path else '',
    )


def _allowed_library_ids_subquery(*, user_id: int) -> Select[tuple[str]]:
    uid = int(user_id)
    shared_subq = (
        select(LibraryShare.library_id)
        .where(LibraryShare.shared_with_user_id == uid)
        .where(LibraryShare.status == 'accepted')
    )
    return select(Library.id).where(
        or_(
            Library.owner_user_id == uid,
            Library.scope == 'global',
            Library.id.in_(shared_subq),
        )
    )


def _apply_smart_marker_filters(
    stmt: Select,
    *,
    marker: Marker,
    query: dict[str, Any] | None,
    user_id: int | None,
) -> Select:
    # Smart markers always respect library access.
    if user_id is not None:
        stmt = stmt.where(Paper.library_id.in_(_allowed_library_ids_subquery(user_id=int(user_id))))

    if _smart_query_is_effectively_empty(query):
        return stmt.where(false())

    root = (query or {}).get('root')
    if not isinstance(root, dict):
        return stmt.where(false())

    def _is_empty_text(col: Any) -> Any:
        return func.length(func.trim(func.coalesce(col, ''))) == 0

    def _ci(col: Any) -> Any:
        return func.lower(func.coalesce(col, ''))

    def _rule_clause(node: dict[str, Any]) -> Any:
        field = str(node.get('field') or '').strip().lower()
        op = str(node.get('operator') or '').strip().lower()
        value = node.get('value')

        # Tags are normalized as a list.
        if field == 'tags':
            values = _normalize_list(value if isinstance(value, list) else ([value] if isinstance(value, str) else None))
            if op in {'empty', 'is_empty'}:
                return ~exists(select(1).select_from(PaperTag).where(PaperTag.paper_id == Paper.id))
            if op in {'not_empty', 'is_not_empty'}:
                return exists(select(1).select_from(PaperTag).where(PaperTag.paper_id == Paper.id))
            if not values:
                return None

            if op in {'includes_all', 'all'}:
                return and_(
                    *[
                        exists(
                            select(1)
                            .select_from(PaperTag)
                            .join(Tag, Tag.id == PaperTag.tag_id)
                            .where(PaperTag.paper_id == Paper.id)
                            .where(Tag.name == v)
                        )
                        for v in values
                    ]
                )
            # default: includes_any
            return exists(
                select(1)
                .select_from(PaperTag)
                .join(Tag, Tag.id == PaperTag.tag_id)
                .where(PaperTag.paper_id == Paper.id)
                .where(Tag.name.in_(values))
            )

        if field == 'markers':
            values = _normalize_list(value if isinstance(value, list) else ([value] if isinstance(value, str) else None))
            if op in {'empty', 'is_empty'}:
                return ~exists(select(1).select_from(PaperMarker).where(PaperMarker.paper_id == Paper.id))
            if op in {'not_empty', 'is_not_empty'}:
                return exists(select(1).select_from(PaperMarker).where(PaperMarker.paper_id == Paper.id))
            if not values:
                return None

            if op in {'includes_all', 'all'}:
                return and_(
                    *[
                        exists(
                            select(1)
                            .select_from(PaperMarker)
                            .where(PaperMarker.paper_id == Paper.id)
                            .where(PaperMarker.marker_id == v)
                        )
                        for v in values
                    ]
                )

            return exists(
                select(1)
                .select_from(PaperMarker)
                .where(PaperMarker.paper_id == Paper.id)
                .where(PaperMarker.marker_id.in_(values))
            )

        # Field mapping (text columns)
        text_cols: dict[str, Any] = {
            'title': Paper.title,
            'subtitle': Paper.subtitle,
            'authors': Paper.authors,
            'publisher': Paper.publisher,
            'journal': Paper.journal,
            'doi': Paper.doi,
            'isbn': Paper.isbn,
            'language': Paper.language,
            'genres': Paper.genres,
            'keywords': Paper.keywords,
            'year': Paper.published_year,
            'published_year': Paper.published_year,
            'file_path': Paper.file_path,
        }
        if field in text_cols:
            col = text_cols[field]
            if op in {'empty', 'is_empty'}:
                return _is_empty_text(col)
            if op in {'not_empty', 'is_not_empty'}:
                return ~_is_empty_text(col)

            v = ''
            if isinstance(value, str):
                v = value.strip()
            if not v:
                return None

            if op == 'equals':
                return _ci(col) == v.lower()
            if op in {'not_equals', 'neq'}:
                return _ci(col) != v.lower()
            if op == 'contains':
                return _ci(col).like(f"%{v.lower()}%")
            if op in {'not_contains', 'does_not_contain'}:
                return ~_ci(col).like(f"%{v.lower()}%")
            return None

        # Exact-match fields
        if field == 'file_type':
            v = str(value or '').strip().lower()
            if not v:
                return None
            if op in {'not_equals', 'neq'}:
                return func.lower(func.coalesce(Paper.file_type, '')) != v
            return func.lower(func.coalesce(Paper.file_type, '')) == v

        if field == 'library_id':
            v = str(value or '').strip()
            if not v:
                return None
            if op in {'not_equals', 'neq'}:
                return Paper.library_id != v
            return Paper.library_id == v

        return None

    def _node_clause(node: Any) -> Any:
        if not isinstance(node, dict):
            return None
        ntype = str(node.get('type') or '').strip().lower()
        if ntype == 'rule':
            return _rule_clause(node)
        if ntype == 'group':
            op = str(node.get('op') or 'and').strip().lower()
            children = node.get('children')
            if not isinstance(children, list):
                return None
            clauses = [c for c in (_node_clause(ch) for ch in children) if c is not None]
            if not clauses:
                return None
            if op == 'or':
                return or_(*clauses)
            return and_(*clauses)
        return None

    clause = _node_clause(root)
    if clause is None:
        return stmt.where(false())
    return stmt.where(clause)


def list_marker_papers(*, user_id: int | None = None, marker_id: str, limit: int = 200) -> list[PaperItem]:
    marker_id = str(marker_id or '').strip()
    if not marker_id:
        return []

    with get_session() as session:
        marker = session.get(Marker, marker_id)
        if marker is None:
            return []

        if bool(marker.is_smart):
            query = _parse_smart_query_v2(marker.rules_json or '')
            stmt = select(Paper).where(_NOT_DELETED)
            stmt = _apply_smart_marker_filters(stmt, marker=marker, query=query, user_id=user_id)
            stmt = stmt.order_by(Paper.created_at.desc()).limit(int(limit))
            rows = session.execute(stmt).scalars().all()

            if user_id is None or not rows:
                return [_paper_item_from_row(r) for r in rows]

            fav_ids = {
                str(x)
                for x in session.execute(
                    select(PaperFavorite.paper_id)
                    .where(PaperFavorite.user_id == int(user_id))
                    .where(PaperFavorite.paper_id.in_([str(r.id) for r in rows]))
                ).scalars().all()
            }

            to_read_ids = {
                str(x)
                for x in session.execute(
                    select(PaperToRead.paper_id)
                    .where(PaperToRead.user_id == int(user_id))
                    .where(PaperToRead.paper_id.in_([str(r.id) for r in rows]))
                ).scalars().all()
            }
            return [
                _paper_item_from_row(
                    r,
                    is_favorite=(str(r.id) in fav_ids),
                    is_to_read=(str(r.id) in to_read_ids),
                )
                for r in rows
            ]

        # Manual marker
        stmt = (
            select(Paper).where(_NOT_DELETED)
            .join(PaperMarker, PaperMarker.paper_id == Paper.id)
            .where(PaperMarker.marker_id == marker_id)
            .order_by(Paper.created_at.desc())
            .limit(int(limit))
        )

        if user_id is not None:
            stmt = stmt.where(Paper.library_id.in_(_allowed_library_ids_subquery(user_id=int(user_id))))
        rows = session.execute(stmt).scalars().all()

        if user_id is None or not rows:
            return [_paper_item_from_row(r) for r in rows]

        fav_ids = {
            str(x)
            for x in session.execute(
                select(PaperFavorite.paper_id)
                .where(PaperFavorite.user_id == int(user_id))
                .where(PaperFavorite.paper_id.in_([str(r.id) for r in rows]))
            ).scalars().all()
        }

        to_read_ids = {
            str(x)
            for x in session.execute(
                select(PaperToRead.paper_id)
                .where(PaperToRead.user_id == int(user_id))
                .where(PaperToRead.paper_id.in_([str(r.id) for r in rows]))
            ).scalars().all()
        }
        return [
            _paper_item_from_row(
                r,
                is_favorite=(str(r.id) in fav_ids),
                is_to_read=(str(r.id) in to_read_ids),
            )
            for r in rows
        ]


def get_markers_for_papers(*, user_id: int | None = None, paper_ids: list[str]) -> dict[str, list[MarkerItem]]:
    paper_ids = [str(pid).strip() for pid in paper_ids if str(pid).strip()]
    if not paper_ids:
        return {}

    result: dict[str, list[MarkerItem]] = {pid: [] for pid in paper_ids}

    with get_session() as session:
        stmt = select(Marker).order_by(Marker.name.asc())
        if user_id is not None:
            stmt = stmt.where(or_(Marker.owner_user_id == int(user_id), Marker.visibility == 'global'))

        markers = session.execute(stmt).scalars().all()
        if not markers:
            return result

        # 1. Map manual markers
        manual_marker_ids = [str(m.id) for m in markers if not bool(m.is_smart)]
        if manual_marker_ids:
            pm_stmt = (
                select(PaperMarker.paper_id, PaperMarker.marker_id)
                .where(PaperMarker.paper_id.in_(paper_ids))
                .where(PaperMarker.marker_id.in_(manual_marker_ids))
            )
            for pid, mid in session.execute(pm_stmt).all():
                pid, mid = str(pid), str(mid)
                marker = next((m for m in markers if str(m.id) == mid), None)
                if marker:
                    m_item = MarkerItem(
                        id=str(marker.id),
                        name=marker.name,
                        icon=marker.icon or 'category',
                        is_smart=False,
                        scope=str(marker.scope or 'all'),
                        paper_count=0,
                        owner_user_id=marker.owner_user_id,
                        visibility=marker.visibility,
                        is_owned_by_me=bool(marker.owner_user_id == user_id) if user_id else False,
                    )
                    if pid in result:
                        result[pid].append(m_item)

        # 2. Evaluate smart markers
        smart_markers = [m for m in markers if bool(m.is_smart)]
        for m in smart_markers:
            query = _parse_smart_query_v2(m.rules_json or '')
            if _smart_query_is_effectively_empty(query):
                continue

            c_stmt = select(Paper.id).where(Paper.id.in_(paper_ids))
            c_stmt = _apply_smart_marker_filters(c_stmt, marker=m, query=query, user_id=user_id)
            matching_pids = [str(r) for r in session.execute(c_stmt).scalars().all()]

            if matching_pids:
                m_item = MarkerItem(
                    id=str(m.id),
                    name=m.name,
                    icon=m.icon or 'category',
                    is_smart=True,
                    scope=str(m.scope or 'all'),
                    paper_count=0,
                    owner_user_id=m.owner_user_id,
                    visibility=m.visibility,
                    is_owned_by_me=bool(m.owner_user_id == user_id) if user_id else False,
                )
                for pid in matching_pids:
                    if pid in result:
                        result[pid].append(m_item)

    return result


__all__ = [
    'list_markers',
    'get_marker',
    'create_marker',
    'update_marker',
    'delete_marker',
    'list_paper_markers',
    'set_paper_markers',
    'list_marker_papers_filtered',
    'list_marker_papers',
    'get_markers_for_papers',
]
