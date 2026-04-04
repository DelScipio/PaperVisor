"""
OPDS Service Layer

This module provides the core content organization logic for OPDS.
It serves as the single source of truth for querying papers, libraries, markers, and other
content entities with proper access control.

OPDS Architecture:
- All queries include user-based access control (library scope, marker visibility)
- Functions return raw Paper objects for consumers to transform
- OPDS HTTP API transforms to Atom/XML feeds
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence
from xml.etree import ElementTree as ET

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

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
from papervisor.db.session import get_session, use_session
from papervisor.domain import MarkerItem

# Exclude soft-deleted papers from all OPDS feeds.
_NOT_DELETED = Paper.deleted_at.is_(None)


def _first_author(authors: str | None) -> str | None:
    """Return the first author from a delimiter-separated authors string."""
    if not authors:
        return None
    first = str(authors).replace(';', ',').split(',', 1)[0].strip()
    return first or None


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class OPDSPaperEntry:
    """Represents a paper in OPDS format with all necessary metadata."""
    paper_id: str
    title: str
    subtitle: str | None
    authors: str | None
    published_year: str | None
    file_type: str
    file_path: str | None
    
    # Metadata
    description: str | None
    abstract: str | None
    language: str | None
    genres: str | None
    series: str | None
    series_index: str | None
    page_count: int | None
    
    # Paper-specific
    doi: str | None
    isbn: str | None
    journal: str | None
    publisher: str | None
    url: str | None
    keywords: str | None
    
    # Reading state
    reading_progress: float
    is_completed: bool
    
    # Timestamps
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime | None


@dataclass
class OPDSNavEntry:
    """Represents a navigation entry in OPDS feeds."""
    id: str
    title: str
    href: str
    content: str
    count: int | None = None
    feed_kind: str = 'acquisition'


@dataclass
class OPDSFacetLink:
    """Represents an OPDS facet link (for reordering/filtering feed views)."""
    href: str
    title: str
    facet_group: str = 'Reorder'
    active: bool = False


# ============================================================================
# Access Control Helpers
# ============================================================================

def get_accessible_library_ids(session: Session, user_id: int) -> list[str]:
    """
    Get list of library IDs that a user can access.
    
    Includes:
    - Libraries owned by the user
    - Libraries shared with the user (accepted shares)
    - Global-scope libraries
    """
    shared_subq = (
        select(LibraryShare.library_id)
        .where(LibraryShare.shared_with_user_id == user_id)
        .where(LibraryShare.status == 'accepted')
    )
    
    lib_rows = session.execute(
        select(Library.id)
        .where(
            or_(
                Library.owner_user_id == user_id,
                Library.scope == 'global',
                Library.id.in_(shared_subq),
            )
        )
    ).scalars().all()
    
    return [str(lib_id) for lib_id in lib_rows]


def get_accessible_marker_ids(session: Session, user_id: int, scope: str | None = None) -> list[str]:
    """
    Get list of marker IDs that a user can access.
    
    Includes:
    - Markers owned by the user
    - Global-visibility markers
    - Optionally filter by scope ('all', 'book', 'paper')
    """
    stmt = select(Marker.id).where(
        or_(
            Marker.owner_user_id == user_id,
            Marker.visibility == 'global',
        )
    )
    
    if scope:
        stmt = stmt.where(Marker.scope == scope)
    
    marker_rows = session.execute(stmt).scalars().all()
    return [str(mid) for mid in marker_rows]


def get_accessible_marker_ids_list(user_id: int, scope: str | None = None) -> list[str]:
    """Wrapper for get_accessible_marker_ids that manages its own session."""
    with get_session() as session:
        return get_accessible_marker_ids(session, user_id, scope)


# ============================================================================
# Core Query Functions
# ============================================================================

def get_all_papers(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = 'az',
    file_type: str | None = None,
) -> list[Paper]:
    """
    Get all papers accessible to the user.
    
    Args:
        user_id: User ID for access control
        limit: Maximum number of papers to return
        offset: Offset for pagination
        sort_by: Sort order ('az', 'za', 'newest', 'oldest', 'author', 'popular')
        file_type: Optional filter by file type ('paper', 'book')
    """
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return []
        
        stmt = select(Paper).where(_NOT_DELETED).where(Paper.library_id.in_(lib_ids))
        
        if file_type:
            stmt = stmt.where(Paper.file_type == file_type)
        
        # Apply sorting
        if sort_by == 'newest':
            stmt = stmt.order_by(Paper.created_at.desc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.created_at.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.title.desc())
        elif sort_by == 'author':
            stmt = stmt.order_by(Paper.authors.asc())
        elif sort_by == 'popular':
            stmt = stmt.order_by(Paper.open_count_total.desc())
        else:  # az
            stmt = stmt.order_by(Paper.title.asc())
        
        stmt = stmt.limit(limit).offset(offset)
        
        return list(session.execute(stmt).scalars().all())


def get_recent_papers(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = 'newest',
) -> list[Paper]:
    """Get recently added papers accessible to the user."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return []
        
        stmt = select(Paper).where(_NOT_DELETED).where(Paper.library_id.in_(lib_ids))

        if sort_by == 'az':
            stmt = stmt.order_by(Paper.title.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.title.desc(), Paper.title.asc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.created_at.asc(), Paper.title.asc())
        elif sort_by == 'author':
            stmt = stmt.order_by(Paper.authors.asc(), Paper.title.asc())
        elif sort_by == 'popular':
            stmt = stmt.order_by(Paper.open_count_total.desc(), Paper.title.asc())
        else:
            stmt = stmt.order_by(Paper.created_at.desc(), Paper.title.asc())

        stmt = stmt.limit(limit).offset(offset)
        
        return list(session.execute(stmt).scalars().all())


def get_popular_papers(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = 'popular',
) -> list[Paper]:
    """Get most opened papers accessible to the user."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return []
        
        stmt = select(Paper).where(_NOT_DELETED).where(Paper.library_id.in_(lib_ids))

        if sort_by == 'az':
            stmt = stmt.order_by(Paper.title.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.title.desc(), Paper.title.asc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.created_at.asc(), Paper.title.asc())
        elif sort_by == 'author':
            stmt = stmt.order_by(Paper.authors.asc(), Paper.title.asc())
        elif sort_by == 'newest':
            stmt = stmt.order_by(Paper.created_at.desc(), Paper.title.asc())
        else:
            stmt = stmt.order_by(Paper.open_count_total.desc(), Paper.title.asc())

        stmt = stmt.limit(limit).offset(offset)
        
        return list(session.execute(stmt).scalars().all())


def get_library_papers(
    user_id: int,
    library_id: str,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = 'az',
) -> list[Paper]:
    """Get papers in a specific library."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if library_id not in lib_ids:
            return []
        
        stmt = select(Paper).where(_NOT_DELETED).where(Paper.library_id == library_id)
        
        if sort_by == 'newest':
            stmt = stmt.order_by(Paper.created_at.desc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.created_at.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.title.desc())
        elif sort_by == 'popular':
            stmt = stmt.order_by(Paper.open_count_total.desc())
        else:
            stmt = stmt.order_by(Paper.title.asc())
        
        stmt = stmt.limit(limit).offset(offset)
        
        return list(session.execute(stmt).scalars().all())


def get_marker_papers(
    user_id: int,
    marker_id: str,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = 'az',
) -> list[Paper]:
    """Get papers in a specific marker (both manual and smart markers)."""
    from papervisor.services.markers import list_marker_papers_filtered
    
    marker_ids = get_accessible_marker_ids_list(user_id)
    if marker_id not in marker_ids:
        return []
    
    # Sort mapping for list_marker_papers_filtered
    sort_param = 'recent' if sort_by == 'newest' else 'popular' if sort_by == 'popular' else 'title_asc'
    
    # Use list_marker_papers_filtered to handle both manual and smart markers
    # Note: This function handles its own pagination, so we pass limit directly
    # For offset, we'll need to increase the limit and slice
    fetch_limit = limit + offset if offset > 0 else limit
    
    paper_items = list_marker_papers_filtered(
        user_id=user_id,
        marker_id=marker_id,
        sort=sort_param,
        limit=fetch_limit,
    )
    
    # Apply offset by slicing
    if offset > 0:
        paper_items = paper_items[offset:]
    
    if not paper_items:
        return []
    
    # Convert PaperItem IDs to Paper ORM objects
    with get_session() as session:
        paper_ids = [p.id for p in paper_items]
        stmt = select(Paper).where(_NOT_DELETED).where(Paper.id.in_(paper_ids))
        papers = list(session.execute(stmt).scalars().all())
        
        # Preserve original order from paper_items
        paper_map = {p.id: p for p in papers}
        return [paper_map[pid] for pid in paper_ids if pid in paper_map]


def get_user_favorites(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = 'az',
) -> list[Paper]:
    """Get user's favorite papers."""
    with get_session() as session:
        paper_ids = session.execute(
            select(PaperFavorite.paper_id)
            .where(PaperFavorite.user_id == user_id)
        ).scalars().all()
        
        if not paper_ids:
            return []
        
        lib_ids = get_accessible_library_ids(session, user_id)
        
        stmt = (
            select(Paper).where(_NOT_DELETED)
            .where(Paper.id.in_(paper_ids))
            .where(Paper.library_id.in_(lib_ids))
        )

        if sort_by == 'newest':
            stmt = stmt.order_by(Paper.created_at.desc(), Paper.title.asc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.created_at.asc(), Paper.title.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.title.desc(), Paper.title.asc())
        elif sort_by == 'author':
            stmt = stmt.order_by(Paper.authors.asc(), Paper.title.asc())
        elif sort_by == 'popular':
            stmt = stmt.order_by(Paper.open_count_total.desc(), Paper.title.asc())
        else:
            stmt = stmt.order_by(Paper.title.asc())

        stmt = stmt.limit(limit).offset(offset)
        
        return list(session.execute(stmt).scalars().all())


def get_user_to_read(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = 'az',
) -> list[Paper]:
    """Get user's to-read papers."""
    with get_session() as session:
        paper_ids = session.execute(
            select(PaperToRead.paper_id)
            .where(PaperToRead.user_id == user_id)
        ).scalars().all()
        
        if not paper_ids:
            return []
        
        lib_ids = get_accessible_library_ids(session, user_id)
        
        stmt = (
            select(Paper).where(_NOT_DELETED)
            .where(Paper.id.in_(paper_ids))
            .where(Paper.library_id.in_(lib_ids))
        )

        if sort_by == 'newest':
            stmt = stmt.order_by(Paper.created_at.desc(), Paper.title.asc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.created_at.asc(), Paper.title.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.title.desc(), Paper.title.asc())
        elif sort_by == 'author':
            stmt = stmt.order_by(Paper.authors.asc(), Paper.title.asc())
        elif sort_by == 'popular':
            stmt = stmt.order_by(Paper.open_count_total.desc(), Paper.title.asc())
        else:
            stmt = stmt.order_by(Paper.title.asc())

        stmt = stmt.limit(limit).offset(offset)
        
        return list(session.execute(stmt).scalars().all())


def get_user_reading(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = 'newest',
) -> list[Paper]:
    """Get papers user is currently reading (progress > 0, not completed)."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return []
        
        stmt = (
            select(Paper).where(_NOT_DELETED)
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.reading_progress > 0)
            .where(Paper.is_completed == False)
        )

        if sort_by == 'az':
            stmt = stmt.order_by(Paper.title.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.title.desc(), Paper.title.asc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.last_read_at.asc(), Paper.title.asc())
        elif sort_by == 'author':
            stmt = stmt.order_by(Paper.authors.asc(), Paper.title.asc())
        elif sort_by == 'popular':
            stmt = stmt.order_by(Paper.open_count_total.desc(), Paper.title.asc())
        else:
            stmt = stmt.order_by(Paper.last_read_at.desc(), Paper.title.asc())

        stmt = stmt.limit(limit).offset(offset)
        
        return list(session.execute(stmt).scalars().all())


def get_user_completed(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = 'newest',
) -> list[Paper]:
    """Get papers user has completed reading."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return []
        
        stmt = (
            select(Paper).where(_NOT_DELETED)
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.is_completed == True)
        )

        if sort_by == 'az':
            stmt = stmt.order_by(Paper.title.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.title.desc(), Paper.title.asc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.last_read_at.asc(), Paper.title.asc())
        elif sort_by == 'author':
            stmt = stmt.order_by(Paper.authors.asc(), Paper.title.asc())
        elif sort_by == 'popular':
            stmt = stmt.order_by(Paper.open_count_total.desc(), Paper.title.asc())
        else:
            stmt = stmt.order_by(Paper.last_read_at.desc(), Paper.title.asc())

        stmt = stmt.limit(limit).offset(offset)
        
        return list(session.execute(stmt).scalars().all())


def get_user_favorites_count(user_id: int) -> int:
    """Get count of user's favorite papers accessible to the user."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)

        if not lib_ids:
            return 0

        count = session.execute(
            select(func.count(func.distinct(Paper.id)))
            .join(PaperFavorite, PaperFavorite.paper_id == Paper.id)
            .where(_NOT_DELETED)
            .where(PaperFavorite.user_id == user_id)
            .where(Paper.library_id.in_(lib_ids))
        ).scalar_one()

        return int(count)


def get_user_to_read_count(user_id: int) -> int:
    """Get count of user's to-read papers accessible to the user."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)

        if not lib_ids:
            return 0

        count = session.execute(
            select(func.count(func.distinct(Paper.id)))
            .join(PaperToRead, PaperToRead.paper_id == Paper.id)
            .where(_NOT_DELETED)
            .where(PaperToRead.user_id == user_id)
            .where(Paper.library_id.in_(lib_ids))
        ).scalar_one()

        return int(count)


def get_user_reading_count(user_id: int) -> int:
    """Get count of papers user is currently reading."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)

        if not lib_ids:
            return 0

        count = session.execute(
            select(func.count(Paper.id))
            .where(_NOT_DELETED)
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.reading_progress > 0)
            .where(Paper.is_completed == False)
        ).scalar_one()

        return int(count)


def get_user_completed_count(user_id: int) -> int:
    """Get count of papers user has completed reading."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)

        if not lib_ids:
            return 0

        count = session.execute(
            select(func.count(Paper.id))
            .where(_NOT_DELETED)
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.is_completed == True)
        ).scalar_one()

        return int(count)


# ============================================================================
# Navigation List Functions
# ============================================================================

def get_libraries(user_id: int) -> list[tuple[Library, int]]:
    """Get all accessible libraries with paper counts."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return []
        
        # Get paper counts per library
        counts_raw = session.execute(
            select(Paper.library_id, func.count(Paper.id))
            .where(Paper.library_id.in_(lib_ids))
            .group_by(Paper.library_id)
        ).all()
        counts = {str(lid): int(cnt) for lid, cnt in counts_raw if lid}
        
        # Get library objects
        libs = session.execute(
            select(Library)
            .where(Library.id.in_(lib_ids))
            .order_by(Library.name.asc())
        ).scalars().all()
        
        return [(lib, counts.get(lib.id, 0)) for lib in libs]


def get_library_name(user_id: int, library_id: str) -> str | None:
    """Return accessible library display name for a library ID."""
    clean_library_id = str(library_id or '').strip()
    if not clean_library_id:
        return None

    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        if clean_library_id not in lib_ids:
            return None

        library = session.execute(
            select(Library)
            .where(Library.id == clean_library_id)
        ).scalar_one_or_none()
        if library is None:
            return None

        name = str(getattr(library, 'name', '') or '').strip()
        return name or None


def get_markers(user_id: int, scope: str | None = None) -> list[tuple[Marker, int]]:
    """Get all accessible markers with paper counts."""
    with get_session() as session:
        marker_ids = get_accessible_marker_ids(session, user_id, scope=scope)
        
        if not marker_ids:
            return []
        
        # Get paper counts for manual markers via assignment table.
        lib_ids = get_accessible_library_ids(session, user_id)
        counts_raw = session.execute(
            select(PaperMarker.marker_id, func.count(func.distinct(PaperMarker.paper_id)))
            .join(Paper, Paper.id == PaperMarker.paper_id)
            .where(_NOT_DELETED)
            .where(PaperMarker.marker_id.in_(marker_ids))
            .where(Paper.library_id.in_(lib_ids))
            .group_by(PaperMarker.marker_id)
        ).all()
        manual_counts = {str(mid): int(cnt) for mid, cnt in counts_raw if mid}
        
        # Get marker objects
        markers = session.execute(
            select(Marker)
            .where(Marker.id.in_(marker_ids))
            .order_by(Marker.name.asc())
        ).scalars().all()

        # Smart markers are not represented in PaperMarker; evaluate their rules.
        from papervisor.services.markers import (
            _apply_smart_marker_filters,
            _parse_smart_query_v2,
            _smart_query_is_effectively_empty,
        )

        smart_counts: dict[str, int] = {}
        for marker in markers:
            marker_id = str(marker.id)
            if not bool(getattr(marker, 'is_smart', False)):
                continue

            query = _parse_smart_query_v2(marker.rules_json or '')
            if _smart_query_is_effectively_empty(query):
                smart_counts[marker_id] = 0
                continue

            c_stmt = select(func.count(func.distinct(Paper.id))).where(_NOT_DELETED)
            c_stmt = _apply_smart_marker_filters(c_stmt, marker=marker, query=query, user_id=user_id)
            smart_counts[marker_id] = int(session.execute(c_stmt).scalar_one() or 0)
        
        return [
            (
                marker,
                smart_counts.get(str(marker.id), manual_counts.get(str(marker.id), 0)),
            )
            for marker in markers
        ]


def get_marker(user_id: int, marker_id: str) -> Marker | None:
    """Get a single accessible marker by id."""
    clean_marker_id = str(marker_id or '').strip()
    if not clean_marker_id:
        return None

    with get_session() as session:
        marker_ids = get_accessible_marker_ids(session, user_id)
        if clean_marker_id not in marker_ids:
            return None

        return session.execute(
            select(Marker)
            .where(Marker.id == clean_marker_id)
        ).scalar_one_or_none()


def get_authors(user_id: int, file_type: str | None = None) -> list[tuple[str, int]]:
    """Get list of authors with paper counts.
    
    Args:
        user_id: User ID for access control
        file_type: Optional filter ('book' or 'paper')
    """
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return []
        
        # Build query
        stmt = (
            select(Paper.authors)
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.authors.isnot(None))
            .where(Paper.authors != '')
        )
        
        # Apply file type filter if provided
        if file_type in ('book', 'paper'):
            stmt = stmt.where(Paper.file_type == file_type)
        
        # Get all papers with authors
        papers = session.execute(stmt).scalars().all()
        
        # Count occurrences of first author only
        author_counts: dict[str, int] = {}
        for authors_str in papers:
            author = _first_author(authors_str)
            if author:
                author_counts[author] = author_counts.get(author, 0) + 1
        
        # Sort by count descending, then alphabetically
        sorted_authors = sorted(
            author_counts.items(),
            key=lambda x: (-x[1], x[0])
        )
        
        return sorted_authors


def get_series(user_id: int) -> list[tuple[str, int]]:
    """Get list of series with book counts (books only)."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return []
        
        # Get series with counts
        series_raw = session.execute(
            select(Paper.series, func.count(Paper.id))
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.file_type == 'book')
            .where(Paper.series.isnot(None))
            .where(Paper.series != '')
            .group_by(Paper.series)
            .order_by(Paper.series.asc())
        ).all()
        
        return [(str(series), int(cnt)) for series, cnt in series_raw if series]


def get_genres(user_id: int) -> list[tuple[str, int]]:
    """Get list of genres with book counts (books only)."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return []
        
        # Get all books with genres
        books = session.execute(
            select(Paper.genres)
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.file_type == 'book')
            .where(Paper.genres.isnot(None))
            .where(Paper.genres != '')
        ).scalars().all()
        
        # Count occurrences of each genre
        genre_counts: dict[str, int] = {}
        for genres_str in books:
            if not genres_str:
                continue
            # Split by common delimiters
            for genre in genres_str.replace(';', ',').split(','):
                genre = genre.strip()
                if genre:
                    genre_counts[genre] = genre_counts.get(genre, 0) + 1
        
        # Sort by count descending, then alphabetically
        sorted_genres = sorted(
            genre_counts.items(),
            key=lambda x: (-x[1], x[0])
        )
        
        return sorted_genres


def get_languages(user_id: int, file_type: str | None = None) -> list[tuple[str, int]]:
    """Get list of languages with counts."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)

        if not lib_ids:
            return []

        stmt = (
            select(Paper.language, func.count(Paper.id))
            .where(_NOT_DELETED)
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.language.isnot(None))
            .where(Paper.language != '')
        )

        if file_type in {'paper', 'book'}:
            stmt = stmt.where(Paper.file_type == file_type)

        rows = (
            stmt.group_by(Paper.language)
            .order_by(func.count(Paper.id).desc(), Paper.language.asc())
        )

        lang_raw = session.execute(rows).all()
        return [(str(language), int(cnt)) for language, cnt in lang_raw if language]


def get_publishers(user_id: int, file_type: str | None = None) -> list[tuple[str, int]]:
    """Get list of publishers with counts."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)

        if not lib_ids:
            return []

        stmt = (
            select(Paper.publisher, func.count(Paper.id))
            .where(_NOT_DELETED)
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.publisher.isnot(None))
            .where(Paper.publisher != '')
        )

        if file_type in {'paper', 'book'}:
            stmt = stmt.where(Paper.file_type == file_type)

        rows = (
            stmt.group_by(Paper.publisher)
            .order_by(func.count(Paper.id).desc(), Paper.publisher.asc())
        )

        pub_raw = session.execute(rows).all()
        return [(str(publisher), int(cnt)) for publisher, cnt in pub_raw if publisher]


def get_tags(user_id: int, file_type: str | None = None) -> list[tuple[str, int]]:
    """Get list of tags with counts."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)

        if not lib_ids:
            return []

        stmt = (
            select(Tag.name, func.count(func.distinct(Paper.id)))
            .join(PaperTag, PaperTag.tag_id == Tag.id)
            .join(Paper, Paper.id == PaperTag.paper_id)
            .where(_NOT_DELETED)
            .where(Paper.library_id.in_(lib_ids))
            .where(Tag.name.isnot(None))
            .where(Tag.name != '')
        )

        if file_type in {'paper', 'book'}:
            stmt = stmt.where(Paper.file_type == file_type)

        rows = (
            stmt.group_by(Tag.name)
            .order_by(func.count(func.distinct(Paper.id)).desc(), Tag.name.asc())
        )

        tag_raw = session.execute(rows).all()
        return [(str(tag_name), int(cnt)) for tag_name, cnt in tag_raw if tag_name]


def get_journals(user_id: int) -> list[tuple[str, int]]:
    """Get list of journals with paper counts (papers only)."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return []
        
        # Get journals with counts
        journals_raw = session.execute(
            select(Paper.journal, func.count(Paper.id))
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.file_type == 'paper')
            .where(Paper.journal.isnot(None))
            .where(Paper.journal != '')
            .group_by(Paper.journal)
            .order_by(Paper.journal.asc())
        ).all()
        
        return [(str(journal), int(cnt)) for journal, cnt in journals_raw if journal]


def get_publication_years(user_id: int) -> list[tuple[str, int]]:
    """Get list of publication years with paper counts."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return []
        
        # Get years with counts
        years_raw = session.execute(
            select(Paper.published_year, func.count(Paper.id))
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.file_type == 'paper')
            .where(Paper.published_year.isnot(None))
            .where(Paper.published_year != '')
            .group_by(Paper.published_year)
            .order_by(Paper.published_year.desc())
        ).all()
        
        return [(str(year), int(cnt)) for year, cnt in years_raw if year]


# ============================================================================
# Filtered Query Functions
# ============================================================================

def get_papers_by_author(
    user_id: int,
    author: str,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = 'az',
) -> list[Paper]:
    """Get papers by a specific author."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return []
        
        stmt = (
            select(Paper).where(_NOT_DELETED)
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.authors.ilike(f'%{author}%'))
        )

        if sort_by == 'newest':
            stmt = stmt.order_by(Paper.created_at.desc(), Paper.title.asc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.created_at.asc(), Paper.title.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.title.desc(), Paper.title.asc())
        elif sort_by == 'author':
            stmt = stmt.order_by(Paper.authors.asc(), Paper.title.asc())
        elif sort_by == 'popular':
            stmt = stmt.order_by(Paper.open_count_total.desc(), Paper.title.asc())
        else:
            stmt = stmt.order_by(Paper.title.asc())

        stmt = stmt.limit(limit).offset(offset)
        
        return list(session.execute(stmt).scalars().all())


def get_papers_by_series(
    user_id: int,
    series: str,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = 'az',
) -> list[Paper]:
    """Get books in a specific series."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return []
        
        stmt = (
            select(Paper).where(_NOT_DELETED)
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.file_type == 'book')
            .where(Paper.series == series)
        )

        if sort_by == 'newest':
            stmt = stmt.order_by(Paper.created_at.desc(), Paper.title.asc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.created_at.asc(), Paper.title.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.series_index.desc(), Paper.title.desc(), Paper.title.asc())
        elif sort_by == 'author':
            stmt = stmt.order_by(Paper.authors.asc(), Paper.title.asc())
        elif sort_by == 'popular':
            stmt = stmt.order_by(Paper.open_count_total.desc(), Paper.title.asc())
        else:
            stmt = stmt.order_by(Paper.series_index.asc(), Paper.title.asc())

        stmt = stmt.limit(limit).offset(offset)
        
        return list(session.execute(stmt).scalars().all())


def get_papers_by_genre(
    user_id: int,
    genre: str,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = 'az',
) -> list[Paper]:
    """Get books by genre."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return []
        
        stmt = (
            select(Paper).where(_NOT_DELETED)
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.file_type == 'book')
            .where(Paper.genres.ilike(f'%{genre}%'))
        )

        if sort_by == 'newest':
            stmt = stmt.order_by(Paper.created_at.desc(), Paper.title.asc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.created_at.asc(), Paper.title.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.title.desc(), Paper.title.asc())
        elif sort_by == 'author':
            stmt = stmt.order_by(Paper.authors.asc(), Paper.title.asc())
        elif sort_by == 'popular':
            stmt = stmt.order_by(Paper.open_count_total.desc(), Paper.title.asc())
        else:
            stmt = stmt.order_by(Paper.title.asc())

        stmt = stmt.limit(limit).offset(offset)
        
        return list(session.execute(stmt).scalars().all())


def get_papers_by_journal(
    user_id: int,
    journal: str,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = 'newest',
) -> list[Paper]:
    """Get papers from a specific journal."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return []
        
        stmt = (
            select(Paper).where(_NOT_DELETED)
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.file_type == 'paper')
            .where(Paper.journal == journal)
        )

        if sort_by == 'az':
            stmt = stmt.order_by(Paper.title.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.title.desc(), Paper.title.asc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.published_year.asc(), Paper.title.asc())
        elif sort_by == 'author':
            stmt = stmt.order_by(Paper.authors.asc(), Paper.title.asc())
        elif sort_by == 'popular':
            stmt = stmt.order_by(Paper.open_count_total.desc(), Paper.title.asc())
        else:
            stmt = stmt.order_by(Paper.published_year.desc(), Paper.title.asc())

        stmt = stmt.limit(limit).offset(offset)
        
        return list(session.execute(stmt).scalars().all())


def get_papers_by_year(
    user_id: int,
    year: str,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = 'az',
) -> list[Paper]:
    """Get papers published in a specific year."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return []
        
        stmt = (
            select(Paper).where(_NOT_DELETED)
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.file_type == 'paper')
            .where(Paper.published_year == year)
        )

        if sort_by == 'newest':
            stmt = stmt.order_by(Paper.created_at.desc(), Paper.title.asc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.created_at.asc(), Paper.title.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.title.desc(), Paper.title.asc())
        elif sort_by == 'author':
            stmt = stmt.order_by(Paper.authors.asc(), Paper.title.asc())
        elif sort_by == 'popular':
            stmt = stmt.order_by(Paper.open_count_total.desc(), Paper.title.asc())
        else:
            stmt = stmt.order_by(Paper.title.asc())

        stmt = stmt.limit(limit).offset(offset)
        
        return list(session.execute(stmt).scalars().all())


def get_papers_by_language(
    user_id: int,
    language: str,
    limit: int = 50,
    offset: int = 0,
    file_type: str | None = None,
    sort_by: str = 'az',
) -> list[Paper]:
    """Get papers in a specific language."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)

        if not lib_ids:
            return []

        stmt = (
            select(Paper).where(_NOT_DELETED)
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.language == language)
        )

        if file_type in {'paper', 'book'}:
            stmt = stmt.where(Paper.file_type == file_type)

        if sort_by == 'newest':
            stmt = stmt.order_by(Paper.created_at.desc(), Paper.title.asc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.created_at.asc(), Paper.title.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.title.desc(), Paper.title.asc())
        elif sort_by == 'author':
            stmt = stmt.order_by(Paper.authors.asc(), Paper.title.asc())
        elif sort_by == 'popular':
            stmt = stmt.order_by(Paper.open_count_total.desc(), Paper.title.asc())
        else:
            stmt = stmt.order_by(Paper.title.asc())

        stmt = stmt.limit(limit).offset(offset)
        return list(session.execute(stmt).scalars().all())


def get_papers_by_publisher(
    user_id: int,
    publisher: str,
    limit: int = 50,
    offset: int = 0,
    file_type: str | None = None,
    sort_by: str = 'az',
) -> list[Paper]:
    """Get papers/books by publisher."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)

        if not lib_ids:
            return []

        stmt = (
            select(Paper).where(_NOT_DELETED)
            .where(Paper.library_id.in_(lib_ids))
            .where(Paper.publisher == publisher)
        )

        if file_type in {'paper', 'book'}:
            stmt = stmt.where(Paper.file_type == file_type)

        if sort_by == 'newest':
            stmt = stmt.order_by(Paper.created_at.desc(), Paper.title.asc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.created_at.asc(), Paper.title.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.title.desc(), Paper.title.asc())
        elif sort_by == 'author':
            stmt = stmt.order_by(Paper.authors.asc(), Paper.title.asc())
        elif sort_by == 'popular':
            stmt = stmt.order_by(Paper.open_count_total.desc(), Paper.title.asc())
        else:
            stmt = stmt.order_by(Paper.title.asc())

        stmt = stmt.limit(limit).offset(offset)
        return list(session.execute(stmt).scalars().all())


def get_papers_by_tag(
    user_id: int,
    tag: str,
    limit: int = 50,
    offset: int = 0,
    file_type: str | None = None,
    sort_by: str = 'az',
) -> list[Paper]:
    """Get papers/books that contain a given tag."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)

        if not lib_ids:
            return []

        stmt = (
            select(Paper)
            .join(PaperTag, PaperTag.paper_id == Paper.id)
            .join(Tag, Tag.id == PaperTag.tag_id)
            .where(_NOT_DELETED)
            .where(Paper.library_id.in_(lib_ids))
            .where(Tag.name == tag)
        )

        if file_type in {'paper', 'book'}:
            stmt = stmt.where(Paper.file_type == file_type)

        if sort_by == 'newest':
            stmt = stmt.order_by(Paper.created_at.desc(), Paper.title.asc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.created_at.asc(), Paper.title.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.title.desc(), Paper.title.asc())
        elif sort_by == 'author':
            stmt = stmt.order_by(Paper.authors.asc(), Paper.title.asc())
        elif sort_by == 'popular':
            stmt = stmt.order_by(Paper.open_count_total.desc(), Paper.title.asc())
        else:
            stmt = stmt.order_by(Paper.title.asc())

        stmt = stmt.limit(limit).offset(offset)
        return list(session.execute(stmt).scalars().all())


def get_complete_acquisition_papers(user_id: int, sort_by: str = 'newest') -> list[Paper]:
    """Get all accessible papers for complete acquisition feeds, newest updates first."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)

        if not lib_ids:
            return []

        stmt = select(Paper).where(_NOT_DELETED).where(Paper.library_id.in_(lib_ids))

        if sort_by == 'az':
            stmt = stmt.order_by(Paper.title.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.title.desc(), Paper.title.asc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.created_at.asc(), Paper.title.asc())
        elif sort_by == 'author':
            stmt = stmt.order_by(Paper.authors.asc(), Paper.title.asc())
        elif sort_by == 'popular':
            stmt = stmt.order_by(Paper.open_count_total.desc(), Paper.title.asc())
        else:
            stmt = stmt.order_by(Paper.updated_at.desc(), Paper.created_at.desc(), Paper.title.asc())

        return list(session.execute(stmt).scalars().all())


def search_papers(
    user_id: int,
    query: str,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = 'az',
) -> list[Paper]:
    """
    Search papers by query string.
    Searches in: title, subtitle, authors, abstract, description, keywords.
    """
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return []
        
        search_term = f'%{query}%'
        
        stmt = (
            select(Paper).where(_NOT_DELETED)
            .where(Paper.library_id.in_(lib_ids))
            .where(
                or_(
                    Paper.title.ilike(search_term),
                    Paper.subtitle.ilike(search_term),
                    Paper.authors.ilike(search_term),
                    Paper.abstract.ilike(search_term),
                    Paper.description.ilike(search_term),
                    Paper.keywords.ilike(search_term),
                )
            )
        )

        if sort_by == 'newest':
            stmt = stmt.order_by(Paper.created_at.desc(), Paper.title.asc())
        elif sort_by == 'oldest':
            stmt = stmt.order_by(Paper.created_at.asc(), Paper.title.asc())
        elif sort_by == 'za':
            stmt = stmt.order_by(Paper.title.desc(), Paper.title.asc())
        elif sort_by == 'author':
            stmt = stmt.order_by(Paper.authors.asc(), Paper.title.asc())
        elif sort_by == 'popular':
            stmt = stmt.order_by(Paper.open_count_total.desc(), Paper.title.asc())
        else:
            stmt = stmt.order_by(Paper.title.asc())

        stmt = stmt.limit(limit).offset(offset)
        
        return list(session.execute(stmt).scalars().all())


def get_paper_by_id(user_id: int, paper_id: str) -> Paper | None:
    """Get a single paper by ID if user has access."""
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        paper = session.execute(
            select(Paper).where(_NOT_DELETED)
            .where(Paper.id == paper_id)
            .where(Paper.library_id.in_(lib_ids))
        ).scalar_one_or_none()
        
        return paper


# ============================================================================
# Statistics
# ============================================================================

def get_total_papers_count(user_id: int, file_type: str | None = None) -> int:
    """Get total count of papers accessible to user.

    Args:
        user_id: User ID for access control.
        file_type: Optional filter by file type ('book' or 'paper').
    """
    with get_session() as session:
        lib_ids = get_accessible_library_ids(session, user_id)
        
        if not lib_ids:
            return 0

        stmt = (
            select(func.count(Paper.id))
            .where(_NOT_DELETED)
            .where(Paper.library_id.in_(lib_ids))
        )

        if file_type in {'book', 'paper'}:
            stmt = stmt.where(Paper.file_type == file_type)

        count = session.execute(stmt).scalar_one()
        
        return int(count)


# ============================================================================
# OPDS Atom Feed Generation
# ============================================================================

# XML namespaces for OPDS
ATOM_NS = 'http://www.w3.org/2005/Atom'
OPDS_NS = 'http://opds-spec.org/2010/catalog'
DCTERMS_NS = 'http://purl.org/dc/terms/'
OPENSEARCH_NS = 'http://a9.com/-/spec/opensearch/1.1/'
FH_NS = 'http://purl.org/syndication/history/1.0'

# Register namespaces
ET.register_namespace('', ATOM_NS)
ET.register_namespace('opds', OPDS_NS)
ET.register_namespace('dcterms', DCTERMS_NS)
ET.register_namespace('opensearch', OPENSEARCH_NS)
ET.register_namespace('fh', FH_NS)


def _format_datetime(dt: datetime | None) -> str:
    """Format datetime for Atom feeds (RFC 3339)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _create_feed_element(
    feed_id: str,
    title: str,
    updated: datetime | None = None,
    subtitle: str | None = None,
) -> ET.Element:
    """Create base feed element with common attributes."""
    feed = ET.Element('feed', {
        'xmlns': ATOM_NS,
    })
    
    id_elem = ET.SubElement(feed, 'id')
    id_elem.text = feed_id
    
    title_elem = ET.SubElement(feed, 'title')
    title_elem.text = title
    
    if subtitle:
        subtitle_elem = ET.SubElement(feed, 'subtitle')
        subtitle_elem.text = subtitle
    
    updated_elem = ET.SubElement(feed, 'updated')
    updated_elem.text = _format_datetime(updated)
    
    author = ET.SubElement(feed, 'author')
    name = ET.SubElement(author, 'name')
    name.text = 'PaperVisor'
    
    return feed


def _add_link(
    parent: ET.Element,
    rel: str,
    href: str,
    type_: str,
    attrs: dict[str, str] | None = None,
    **kwargs: str,
) -> None:
    """Add a link element to parent."""
    link_attrs = {
        'rel': rel,
        'href': href,
        'type': type_,
    }
    link_attrs.update(kwargs)
    if attrs:
        link_attrs.update(attrs)
    ET.SubElement(parent, 'link', link_attrs)


def paper_to_atom_entry(paper: Paper, base_url: str, key_param: str = '', markers: list[MarkerItem] | None = None) -> ET.Element:
    """Convert a Paper to an Atom entry element."""
    from pathlib import Path
    from papervisor.core.config import get_paths
    
    paths = get_paths()

    def _with_key(url: str) -> str:
        kp = str(key_param or '').strip()
        if not kp:
            return url
        if '?' in url:
            return f'{url}&{kp.lstrip("?")}'
        return f'{url}{kp}'

    """Convert a Paper object to an Atom entry element."""
    entry = ET.Element('entry')
    
    # ID
    id_elem = ET.SubElement(entry, 'id')
    id_elem.text = f'urn:papervisor:paper:{paper.id}'
    
    # Title
    title_elem = ET.SubElement(entry, 'title')
    title_elem.text = paper.title
    
    summary_text = str(paper.subtitle or paper.abstract or paper.description or '').strip()
    if summary_text:
        summary_elem = ET.SubElement(entry, 'summary', {'type': 'text'})
        summary_elem.text = summary_text[:700]
    
    # Updated
    updated_elem = ET.SubElement(entry, 'updated')
    updated_elem.text = _format_datetime(paper.updated_at)
    
    # Published (use created_at or publication_date)
    if paper.publication_date:
        published_elem = ET.SubElement(entry, 'published')
        published_elem.text = paper.publication_date
    elif paper.published_year:
        published_elem = ET.SubElement(entry, 'published')
        published_elem.text = f'{paper.published_year}-01-01'
    
    # Authors (first author only)
    author_name = _first_author(paper.authors)
    if author_name:
        author = ET.SubElement(entry, 'author')
        name = ET.SubElement(author, 'name')
        name.text = author_name
    
    content_parts: list[str] = []
    for value in (paper.description, paper.abstract):
        text = str(value or '').strip()
        if text and text not in content_parts:
            content_parts.append(text)

    if not content_parts and paper.subtitle:
        subtitle_text = str(paper.subtitle).strip()
        if subtitle_text:
            content_parts.append(subtitle_text)

    content_text = '\n\n'.join(content_parts)
    if content_text:
        content = ET.SubElement(entry, 'content', {'type': 'text'})
        content.text = content_text[:2000]
    
    # Categories (genres, keywords)
    if paper.genres:
        for genre in paper.genres.replace(';', ',').split(','):
            genre = genre.strip()
            if genre:
                ET.SubElement(entry, 'category', {'term': genre, 'label': genre})
    
    if paper.keywords:
        for keyword in paper.keywords.replace(';', ',').split(',')[:5]:  # Max 5
            keyword = keyword.strip()
            if keyword:
                ET.SubElement(entry, 'category', {'term': keyword, 'label': keyword})
    
    # Markers
    if markers:
        for marker in markers:
            marker_name = str(getattr(marker, 'name', '') or '').strip()
            marker_term = marker_name or str(getattr(marker, 'id', '') or '').strip()
            if not marker_term:
                continue
            ET.SubElement(entry, 'category', {
                'scheme': 'http://papervisor.app/markers',
                'term': marker_term,
                'label': marker_name or marker_term,
            })
    
    # DC Terms metadata
    if paper.language:
        lang = ET.SubElement(entry, f'{{{DCTERMS_NS}}}language')
        lang.text = paper.language
    
    if paper.publisher:
        publisher = ET.SubElement(entry, f'{{{DCTERMS_NS}}}publisher')
        publisher.text = paper.publisher
    
    if paper.published_year:
        issued = ET.SubElement(entry, f'{{{DCTERMS_NS}}}issued')
        issued.text = paper.published_year
    
    if paper.page_count:
        extent = ET.SubElement(entry, f'{{{DCTERMS_NS}}}extent')
        extent.text = f'{paper.page_count} pages'
    
    # Cover image (check both .jpg and .png extensions)
    cover_path_jpg = paths.library_files_dir / '_media' / 'covers' / f'{paper.id}.jpg'
    cover_path_png = paths.library_files_dir / '_media' / 'covers' / f'{paper.id}.png'
    thumb_path_jpg = paths.library_files_dir / '_media' / 'thumbs' / f'{paper.id}.jpg'
    thumb_path_png = paths.library_files_dir / '_media' / 'thumbs' / f'{paper.id}.png'
    
    if cover_path_jpg.exists():
        cover_url = _with_key(f'{base_url}/library_files/_media/covers/{paper.id}.jpg')
        _add_link(entry, 'http://opds-spec.org/image', cover_url, 'image/jpeg')
    elif cover_path_png.exists():
        cover_url = _with_key(f'{base_url}/library_files/_media/covers/{paper.id}.png')
        _add_link(entry, 'http://opds-spec.org/image', cover_url, 'image/png')
    
    if thumb_path_jpg.exists():
        thumb_url = _with_key(f'{base_url}/library_files/_media/thumbs/{paper.id}.jpg')
        _add_link(entry, 'http://opds-spec.org/image/thumbnail', thumb_url, 'image/jpeg')
    elif thumb_path_png.exists():
        thumb_url = _with_key(f'{base_url}/library_files/_media/thumbs/{paper.id}.png')
        _add_link(entry, 'http://opds-spec.org/image/thumbnail', thumb_url, 'image/png')
    
    # Acquisition link - use direct file path (already mounted as static files)
    file_ext = (paper.file_path or '').split('.')[-1].lower() if paper.file_path else 'pdf'
    mime_type = 'application/epub+zip' if file_ext == 'epub' else 'application/pdf'

    acquisition_url = None
    if paper.file_path:
        file_path = Path(paper.file_path)

        # 1) Try direct relative_to library_files_dir
        try:
            relative_path = file_path.relative_to(paths.library_files_dir)
            acquisition_url = f'{base_url}/library_files/{relative_path}'
        except ValueError:
            # 2) If already relative, use it as-is
            if not file_path.is_absolute():
                acquisition_url = f'{base_url}/library_files/{file_path.as_posix()}'
            else:
                # 3) Heuristic: align by folder name (handles old absolute paths)
                lib_parts = list(paths.library_files_dir.parts)
                file_parts = list(file_path.parts)
                lib_tail = lib_parts[-1] if lib_parts else ''
                if lib_tail and lib_tail in file_parts:
                    idx = len(file_parts) - 1 - file_parts[::-1].index(lib_tail)
                    candidate_rel = Path(*file_parts[idx + 1 :])
                    if candidate_rel:
                        candidate_abs = paths.library_files_dir / candidate_rel
                        if candidate_abs.exists():
                            acquisition_url = f'{base_url}/library_files/{candidate_rel.as_posix()}'

    if acquisition_url:
        _add_link(
            entry,
            'http://opds-spec.org/acquisition/open-access',
            _with_key(acquisition_url),
            mime_type,
            title=paper.title
        )
    
    return entry


def generate_navigation_feed(
    feed_id: str,
    title: str,
    entries: list[OPDSNavEntry],
    base_url: str,
    self_href: str,
    subtitle: str | None = None,
    key_param: str = '',
    up_href: str | None = None,
    crawlable_href: str | None = None,
) -> str:
    """Generate an OPDS navigation feed."""
    feed = _create_feed_element(
        feed_id=feed_id,
        title=title,
        subtitle=subtitle,
    )
    
    # Self link
    _add_link(
        feed,
        'self',
        self_href,
        'application/atom+xml;profile=opds-catalog;kind=navigation'
    )
    
    # Start link
    _add_link(
        feed,
        'start',
        f'{base_url}/opds/{key_param}',
        'application/atom+xml;profile=opds-catalog;kind=navigation'
    )

    # Up link (optional)
    if up_href:
        _add_link(
            feed,
            'up',
            up_href,
            'application/atom+xml;profile=opds-catalog;kind=navigation'
        )
    
    # Search link
    _add_link(
        feed,
        'search',
        f'{base_url}/opds/search{key_param}',
        'application/opensearchdescription+xml'
    )

    if crawlable_href:
        _add_link(
            feed,
            'http://opds-spec.org/crawlable',
            crawlable_href,
            'application/atom+xml;profile=opds-catalog;kind=acquisition'
        )
    
    # Add navigation entries
    for nav_entry in entries:
        entry = ET.SubElement(feed, 'entry')
        
        id_elem = ET.SubElement(entry, 'id')
        id_elem.text = nav_entry.id
        
        title_elem = ET.SubElement(entry, 'title')
        title_elem.text = nav_entry.title
        
        updated_elem = ET.SubElement(entry, 'updated')
        updated_elem.text = _format_datetime(None)
        
        content = ET.SubElement(entry, 'content', {'type': 'text'})
        content.text = nav_entry.content
        
        # Add count if available
        if nav_entry.count is not None:
            content.text += f' ({nav_entry.count} items)'
        
        # Link type depends on destination feed kind
        kind = nav_entry.feed_kind if nav_entry.feed_kind in {'acquisition', 'navigation'} else 'acquisition'
        link_type = f'application/atom+xml;profile=opds-catalog;kind={kind}'
        _add_link(entry, 'subsection', nav_entry.href, link_type)
    
    return ET.tostring(feed, encoding='unicode', xml_declaration=True)


def generate_acquisition_feed(
    feed_id: str,
    title: str,
    papers: list[Paper],
    base_url: str,
    self_href: str,
    subtitle: str | None = None,
    next_href: str | None = None,
    prev_href: str | None = None,
    key_param: str = '',
    up_href: str | None = None,
    paper_markers_map: dict[str, list[MarkerItem]] | None = None,
    crawlable_href: str | None = None,
    is_complete_feed: bool = False,
    facets: list[OPDSFacetLink] | None = None,
) -> str:
    """Generate an OPDS acquisition feed."""
    feed = _create_feed_element(
        feed_id=feed_id,
        title=title,
        subtitle=subtitle,
    )
    
    # Self link
    _add_link(
        feed,
        'self',
        self_href,
        'application/atom+xml;profile=opds-catalog;kind=acquisition'
    )
    
    # Start link
    _add_link(
        feed,
        'start',
        f'{base_url}/opds/{key_param}',
        'application/atom+xml;profile=opds-catalog;kind=navigation'
    )

    # Up link (optional)
    if up_href:
        _add_link(
            feed,
            'up',
            up_href,
            'application/atom+xml;profile=opds-catalog;kind=navigation'
        )
    
    # Pagination links
    if next_href:
        _add_link(
            feed,
            'next',
            next_href,
            'application/atom+xml;profile=opds-catalog;kind=acquisition'
        )
    
    if prev_href:
        _add_link(
            feed,
            'previous',
            prev_href,
            'application/atom+xml;profile=opds-catalog;kind=acquisition'
        )

    if crawlable_href:
        _add_link(
            feed,
            'http://opds-spec.org/crawlable',
            crawlable_href,
            'application/atom+xml;profile=opds-catalog;kind=acquisition'
        )

    if is_complete_feed:
        ET.SubElement(feed, f'{{{FH_NS}}}complete')

    if facets:
        for facet in facets:
            facet_attrs = {
                f'{{{OPDS_NS}}}facetGroup': facet.facet_group,
            }
            if facet.active:
                facet_attrs[f'{{{OPDS_NS}}}activeFacet'] = 'true'

            _add_link(
                feed,
                'http://opds-spec.org/facet',
                facet.href,
                'application/atom+xml;profile=opds-catalog;kind=acquisition',
                attrs=facet_attrs,
                title=facet.title,
            )
    
    # Add paper entries
    for paper in papers:
        paper_markers = paper_markers_map.get(str(paper.id)) if paper_markers_map else None
        entry = paper_to_atom_entry(paper, base_url, key_param, markers=paper_markers)
        feed.append(entry)
    
    return ET.tostring(feed, encoding='unicode', xml_declaration=True)


def generate_opensearch_descriptor(base_url: str, key_param: str = '') -> str:
    """Generate OpenSearch description document."""
    key_suffix = ''
    if key_param:
        key_suffix = f'&{str(key_param).lstrip("?")}'

    root = ET.Element('OpenSearchDescription', {
        'xmlns': OPENSEARCH_NS,
    })
    
    short_name = ET.SubElement(root, 'ShortName')
    short_name.text = 'PaperVisor'
    
    description = ET.SubElement(root, 'Description')
    description.text = 'Search papers and books in PaperVisor'
    
    url = ET.SubElement(root, 'Url', {
        'type': 'application/atom+xml;profile=opds-catalog;kind=acquisition',
        'template': f'{base_url}/opds/search/?q={{searchTerms}}{key_suffix}',
    })
    
    return ET.tostring(root, encoding='unicode', xml_declaration=True)
