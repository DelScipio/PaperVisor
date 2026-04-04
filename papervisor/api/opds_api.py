"""
OPDS HTTP API

Provides HTTP endpoints for OPDS catalog access.
Maps HTTP routes to OPDS service layer functions and generates Atom/XML responses.

NOTE: This file is intentionally kept as a single module because all endpoints
use NiceGUI's `app.get()` decorators which register routes at import time.
Common utilities have been extracted to `opds_common.py`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import HTTPException, Request, Response, Depends
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import StreamingResponse
from nicegui import app

from papervisor.services import opds
from papervisor.services.markers import get_markers_for_papers
from papervisor.services.papers import record_opened
from papervisor.services.settings import get_setting
from papervisor.api.opds_common import (
    OPDSContext,
    acquisition_feed_response,
    _browse_author_acquisition_response,
    _browse_named_acquisition_response,
    _browse_named_count_list_response,
    _entity_count_navigation_feed_response,
    _named_entity_acquisition_response,
    _named_count_navigation_feed_response,
    _nav_entries_from_specs,
    _paginated_acquisition,
    _static_menu_navigation_feed_response,
    check_enabled as _check_enabled,
    get_api_key as _get_api_key,
    get_api_key_param as _get_api_key_param,
    get_base_url as _get_base_url,
    opds_context,
)


_USER_MENU_SPECS: list[dict[str, object]] = [
    {
        'id': 'urn:papervisor:opds:user:favorites',
        'title': 'Favorites',
        'path': 'user/favorites',
        'content': 'Your favorite papers and books',
    },
    {
        'id': 'urn:papervisor:opds:user:toread',
        'title': 'To Read',
        'path': 'user/to-read',
        'content': 'Papers you want to read',
    },
    {
        'id': 'urn:papervisor:opds:user:reading',
        'title': 'Currently Reading',
        'path': 'user/reading',
        'content': 'Papers you are currently reading',
    },
    {
        'id': 'urn:papervisor:opds:user:completed',
        'title': 'Completed',
        'path': 'user/completed',
        'content': 'Papers you have finished reading',
    },
]


_BROWSE_MENU_SPECS: list[dict[str, object]] = [
    {
        'id': 'urn:papervisor:opds:browse:papers',
        'title': 'Papers',
        'path': 'browse/papers',
        'content': 'Browse paper-specific facets: authors, journal, tags, year',
        'feed_kind': 'navigation',
    },
    {
        'id': 'urn:papervisor:opds:browse:books',
        'title': 'Books',
        'path': 'browse/books',
        'content': 'Browse book-specific facets: authors, series, genres, publisher, language',
        'feed_kind': 'navigation',
    },
    {
        'id': 'urn:papervisor:opds:browse:authors',
        'title': 'Authors',
        'path': 'authors',
        'content': 'Browse all authors',
        'feed_kind': 'navigation',
    },
    {
        'id': 'urn:papervisor:opds:browse:tags',
        'title': 'Tags',
        'path': 'browse/tags',
        'content': 'Browse by tags',
        'feed_kind': 'navigation',
    },
    {
        'id': 'urn:papervisor:opds:browse:languages',
        'title': 'Languages',
        'path': 'browse/languages',
        'content': 'Browse by language',
        'feed_kind': 'navigation',
    },
]


_ROOT_MENU_STATIC_SPECS: list[dict[str, object]] = [
    {
        'id': 'urn:papervisor:opds:all',
        'title': 'All Files',
        'path': 'all',
        'content': 'Browse all available files (books and papers)',
    },
    {
        'id': 'urn:papervisor:opds:recent',
        'title': 'Recently Added',
        'path': 'recent',
        'content': 'Recently added publications',
    },
    {
        'id': 'urn:papervisor:opds:popular',
        'title': 'Most Popular',
        'path': 'popular',
        'content': 'Most frequently opened publications',
    },
    {
        'id': 'urn:papervisor:opds:browse',
        'title': 'Browse By',
        'path': 'browse',
        'content': 'Browse by type, author, series, journal, and more',
        'feed_kind': 'navigation',
    },
    {
        'id': 'urn:papervisor:opds:libraries',
        'title': 'Libraries',
        'path': 'libraries',
        'content': 'Browse by library',
        'feed_kind': 'navigation',
    },
    {
        'id': 'urn:papervisor:opds:markers',
        'title': 'Markers',
        'path': 'markers',
        'content': 'Browse by marker',
        'feed_kind': 'navigation',
    },
    {
        'id': 'urn:papervisor:opds:user',
        'title': 'My Reading',
        'path': 'user',
        'content': 'Favorites, to-read, and reading progress',
        'feed_kind': 'navigation',
    },
]


def _resolve_library_file_path(file_path: str | None) -> Path | None:
    """Resolve DB-backed file path under library root, rejecting path escapes."""
    raw = str(file_path or '').strip()
    if not raw:
        return None

    from papervisor.core.config import get_paths

    try:
        library_root = get_paths().library_files_dir.resolve()
        rel = Path(raw)
        if rel.is_absolute():
            return None
        candidate = (library_root / rel).resolve()
        candidate.relative_to(library_root)
        return candidate
    except (OSError, ValueError):
        return None


# ============================================================================
# Root Catalog
# ============================================================================

@app.get('/opds/ping')
def ping():
    """Ping endpoint - no auth required."""
    return {'status': 'ok'}

@app.get('/opds/test')
def test_endpoint(ctx: OPDSContext = Depends(opds_context)):
    """Test endpoint to verify OPDS is working."""
    return Response(content=f'<test>Hello {ctx.user.username}!</test>', media_type='text/xml')

@app.get('/opds/')
def root_catalog(ctx: OPDSContext = Depends(opds_context)):
    """OPDS root catalog - main entry point."""
    
    # Get catalog settings
    catalog_title = get_setting(key='opds_title', default='PaperVisor Library')
    catalog_subtitle = get_setting(key='opds_subtitle', default='Browse and download papers and books')
    
    root_specs = [dict(spec) for spec in _ROOT_MENU_STATIC_SPECS]
    for spec in root_specs:
        spec_id = str(spec.get('id') or '')
        if spec_id == 'urn:papervisor:opds:all':
            spec['count'] = opds.get_total_papers_count(ctx.user.id)
        elif spec_id == 'urn:papervisor:opds:recent':
            spec['count'] = opds.get_total_papers_count(ctx.user.id)
        elif spec_id == 'urn:papervisor:opds:popular':
            spec['count'] = opds.get_total_papers_count(ctx.user.id)
        elif spec_id == 'urn:papervisor:opds:browse':
            spec['count'] = len(_BROWSE_MENU_SPECS)
        elif spec_id == 'urn:papervisor:opds:libraries':
            spec['count'] = len(opds.get_libraries(ctx.user.id))
        elif spec_id == 'urn:papervisor:opds:markers':
            spec['count'] = len(opds.get_markers(ctx.user.id))
        elif spec_id == 'urn:papervisor:opds:user':
            spec['count'] = len(_USER_MENU_SPECS)

    entries = _nav_entries_from_specs(
        ctx=ctx,
        specs=root_specs,
    )
    
    return _static_menu_navigation_feed_response(
        ctx=ctx,
        entries=entries,
        feed_id='urn:papervisor:opds:root',
        title=catalog_title,
        subtitle=catalog_subtitle,
        path='',
    )


# ============================================================================
# Acquisition Feeds
# ============================================================================

def _complete_feed_response(*, ctx: OPDSContext, self_path: str, feed_id: str, title: str) -> Response:
    sort_key = ctx.sort_by or 'newest'
    papers = opds.get_complete_acquisition_papers(ctx.user.id, sort_by=sort_key)
    paper_ids = [str(p.id) for p in papers]
    paper_markers_map = get_markers_for_papers(user_id=ctx.user.id, paper_ids=paper_ids) if papers else {}

    return acquisition_feed_response(
        ctx=ctx,
        feed_id=feed_id,
        title=title,
        subtitle='Complete acquisition feed',
        papers=papers,
        path=self_path,
        page=1,
        per_page=max(len(papers), 1),
        query_params={'sort': sort_key},
        paper_markers_map=paper_markers_map,
        supports_sort=True,
        default_sort='newest',
        include_collection_facets=True,
        collection_key='all',
        is_complete_feed=True,
    )


@app.get('/opds/all')
def all_publications(ctx: OPDSContext = Depends(opds_context)):
    """All files feed (complete acquisition feed semantics)."""
    return _complete_feed_response(
        ctx=ctx,
        self_path='all',
        feed_id='urn:papervisor:opds:all',
        title='All Files',
    )


@app.get('/opds/complete')
def complete_acquisition_feed(ctx: OPDSContext = Depends(opds_context)):
    """Alias to complete acquisition feed for crawler compatibility."""
    return _complete_feed_response(
        ctx=ctx,
        self_path='complete',
        feed_id='urn:papervisor:opds:complete',
        title='Complete Acquisition Feed',
    )


@app.get('/opds/recent')
def recent_publications(page: int = 1, per_page: int = 10, ctx: OPDSContext = Depends(opds_context)):
    """Recently added publications."""
    per_page = max(1, min(per_page, 10))
    return _paginated_acquisition(
        ctx=ctx,
        page=page,
        per_page=per_page,
        fetcher=opds.get_recent_papers,
        feed_id='urn:papervisor:opds:recent',
        title='Recently Added',
        subtitle='Recently added publications',
        path='recent',
        default_sort='newest',
    )


@app.get('/opds/popular')
def popular_publications(page: int = 1, per_page: int = 10, ctx: OPDSContext = Depends(opds_context)):
    """Most popular publications."""
    per_page = max(1, min(per_page, 10))
    return _paginated_acquisition(
        ctx=ctx,
        page=page,
        per_page=per_page,
        fetcher=opds.get_popular_papers,
        feed_id='urn:papervisor:opds:popular',
        title='Most Popular',
        subtitle='Most frequently opened publications',
        path='popular',
        default_sort='popular',
    )


@app.get('/opds/books')
def books_only(page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Books only."""
    return _paginated_acquisition(
        ctx=ctx,
        page=page,
        per_page=per_page,
        fetcher=opds.get_all_papers,
        feed_id='urn:papervisor:opds:books',
        title='Books',
        subtitle='Browse books',
        path='books',
        collection_key='books',
        include_collection_facets=True,
        file_type='book',
    )


@app.get('/opds/papers')
def papers_only(page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Academic papers only."""
    return _paginated_acquisition(
        ctx=ctx,
        page=page,
        per_page=per_page,
        fetcher=opds.get_all_papers,
        feed_id='urn:papervisor:opds:papers',
        title='Academic Papers',
        subtitle='Browse academic papers',
        path='papers',
        collection_key='papers',
        include_collection_facets=True,
        file_type='paper',
    )


# ============================================================================
# Libraries Navigation
# ============================================================================

@app.get('/opds/libraries')
def libraries_list(ctx: OPDSContext = Depends(opds_context)):
    """List all accessible libraries."""
    libraries = opds.get_libraries(ctx.user.id)

    return _entity_count_navigation_feed_response(
        ctx=ctx,
        items=libraries,
        id_prefix='urn:papervisor:opds:library:',
        href_prefix='libraries/',
        default_content_template='Papers in {name}',
        content_attr='description',
        feed_id='urn:papervisor:opds:libraries',
        title='Libraries',
        subtitle='Browse by library',
        path='libraries',
    )


@app.get('/opds/libraries/{library_id}')
def library_papers(library_id: str, page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Papers in a specific library."""
    title_value = opds.get_library_name(ctx.user.id, library_id)
    if not title_value:
        raise HTTPException(status_code=404, detail='Library not found')
    return _named_entity_acquisition_response(
        ctx=ctx,
        value=library_id,
        page=page,
        per_page=per_page,
        fetcher=opds.get_library_papers,
        feed_id_prefix='urn:papervisor:opds:library:',
        title_prefix='Library:',
        path_prefix='libraries/',
        title_value=title_value,
        raise_on_empty_first_page=True,
        not_found_detail='Library not found or no papers',
    )


# ============================================================================
# Markers Navigation
# ============================================================================

@app.get('/opds/markers')
def markers_list(ctx: OPDSContext = Depends(opds_context)):
    """List all accessible markers/shelves."""
    markers = opds.get_markers(ctx.user.id)

    return _entity_count_navigation_feed_response(
        ctx=ctx,
        items=markers,
        id_prefix='urn:papervisor:opds:marker:',
        href_prefix='markers/',
        default_content_template='Papers in {name}',
        feed_id='urn:papervisor:opds:markers',
        title='Markers',
        subtitle='Browse by marker',
        path='markers',
    )


@app.get('/opds/markers/{marker_id}')
def marker_papers(marker_id: str, page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Papers in a specific marker."""
    marker = opds.get_marker(ctx.user.id, marker_id)
    if marker is None:
        raise HTTPException(status_code=404, detail='Marker not found')
    marker_name = marker.name

    # Don't raise 404 if marker is empty - just return empty feed.
    return _named_entity_acquisition_response(
        ctx=ctx,
        value=marker_id,
        page=page,
        per_page=per_page,
        fetcher=opds.get_marker_papers,
        feed_id_prefix='urn:papervisor:opds:marker:',
        title_prefix='Marker:',
        path_prefix='markers/',
        up_path='markers',
        title_value=marker_name,
    )


# ============================================================================
# Authors Navigation
# ============================================================================

@app.get('/opds/authors')
def authors_list(ctx: OPDSContext = Depends(opds_context)):
    """List all authors."""
    authors = opds.get_authors(ctx.user.id)

    return _named_count_navigation_feed_response(
        ctx=ctx,
        items=authors,
        id_prefix='urn:papervisor:opds:author:',
        href_prefix='authors/',
        content_template='Papers by {name}',
        feed_id='urn:papervisor:opds:authors',
        title='Authors',
        subtitle='Browse by author',
        path='authors',
        encode_id=True,
        encode_href=True,
    )


@app.get('/opds/authors/{author}')
def author_papers(author: str, page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Papers by a specific author."""
    return _named_entity_acquisition_response(
        ctx=ctx,
        value=author,
        page=page,
        per_page=per_page,
        fetcher=opds.get_papers_by_author,
        feed_id_prefix='urn:papervisor:opds:author:',
        title_prefix='Papers by',
        path_prefix='authors/',
        raise_on_empty_first_page=True,
        not_found_detail='Author not found or no papers',
    )


# ============================================================================
# User-Specific Feeds
# ============================================================================

@app.get('/opds/user')
def user_menu(ctx: OPDSContext = Depends(opds_context)):
    """User-specific navigation menu."""
    user_specs = [dict(spec) for spec in _USER_MENU_SPECS]
    for spec in user_specs:
        spec_id = str(spec.get('id') or '')
        if spec_id == 'urn:papervisor:opds:user:favorites':
            spec['count'] = opds.get_user_favorites_count(ctx.user.id)
        elif spec_id == 'urn:papervisor:opds:user:toread':
            spec['count'] = opds.get_user_to_read_count(ctx.user.id)
        elif spec_id == 'urn:papervisor:opds:user:reading':
            spec['count'] = opds.get_user_reading_count(ctx.user.id)
        elif spec_id == 'urn:papervisor:opds:user:completed':
            spec['count'] = opds.get_user_completed_count(ctx.user.id)

    entries = _nav_entries_from_specs(
        ctx=ctx,
        specs=user_specs,
    )
    
    return _static_menu_navigation_feed_response(
        ctx=ctx,
        entries=entries,
        feed_id='urn:papervisor:opds:user',
        title='My Reading',
        subtitle='Personal reading lists and progress',
        path='user',
    )


@app.get('/opds/user/favorites')
def user_favorites(page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """User's favorite papers."""
    return _paginated_acquisition(
        ctx=ctx,
        page=page,
        per_page=per_page,
        fetcher=opds.get_user_favorites,
        feed_id='urn:papervisor:opds:user:favorites',
        title='My Favorites',
        path='user/favorites',
    )


@app.get('/opds/user/to-read')
def user_to_read(page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """User's to-read papers."""
    return _paginated_acquisition(
        ctx=ctx,
        page=page,
        per_page=per_page,
        fetcher=opds.get_user_to_read,
        feed_id='urn:papervisor:opds:user:toread',
        title='To Read',
        path='user/to-read',
    )


@app.get('/opds/user/reading')
def user_reading(page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Papers user is currently reading."""
    return _paginated_acquisition(
        ctx=ctx,
        page=page,
        per_page=per_page,
        fetcher=opds.get_user_reading,
        feed_id='urn:papervisor:opds:user:reading',
        title='Currently Reading',
        path='user/reading',
    )


@app.get('/opds/user/completed')
def user_completed(page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Papers user has completed."""
    return _paginated_acquisition(
        ctx=ctx,
        page=page,
        per_page=per_page,
        fetcher=opds.get_user_completed,
        feed_id='urn:papervisor:opds:user:completed',
        title='Completed',
        path='user/completed',
    )


# ============================================================================
# Browse By (Filter Categories)
# ============================================================================

@app.get('/opds/browse')
def browse_menu(ctx: OPDSContext = Depends(opds_context)):
    """Browse by category navigation menu."""
    browse_specs = [dict(spec) for spec in _BROWSE_MENU_SPECS]
    for spec in browse_specs:
        spec_id = str(spec.get('id') or '')
        if spec_id == 'urn:papervisor:opds:browse:papers':
            spec['count'] = opds.get_total_papers_count(ctx.user.id, file_type='paper')
        elif spec_id == 'urn:papervisor:opds:browse:books':
            spec['count'] = opds.get_total_papers_count(ctx.user.id, file_type='book')
        elif spec_id == 'urn:papervisor:opds:browse:authors':
            spec['count'] = len(opds.get_authors(ctx.user.id))
        elif spec_id == 'urn:papervisor:opds:browse:tags':
            spec['count'] = len(opds.get_tags(ctx.user.id))
        elif spec_id == 'urn:papervisor:opds:browse:languages':
            spec['count'] = len(opds.get_languages(ctx.user.id))

    entries = _nav_entries_from_specs(
        ctx=ctx,
        specs=browse_specs,
    )
    
    return _static_menu_navigation_feed_response(
        ctx=ctx,
        entries=entries,
        feed_id='urn:papervisor:opds:browse',
        title='Browse By',
        subtitle='Filter by type, author, series, journal, and more',
        path='browse',
        up_href=ctx.url.build(''),
    )


@app.get('/opds/browse/papers')
def browse_papers_menu(ctx: OPDSContext = Depends(opds_context)):
    """Paper facet navigation."""
    paper_authors = opds.get_authors(ctx.user.id, file_type='paper')
    journals = opds.get_journals(ctx.user.id)
    paper_tags = opds.get_tags(ctx.user.id, file_type='paper')
    publication_years = opds.get_publication_years(ctx.user.id)

    specs: list[dict[str, object]] = [
        {
            'id': 'urn:papervisor:opds:browse:paper-authors',
            'title': 'Authors',
            'path': 'browse/paper-authors',
            'content': 'Browse papers by author',
            'count': len(paper_authors),
            'feed_kind': 'navigation',
        },
        {
            'id': 'urn:papervisor:opds:browse:journals',
            'title': 'Journals',
            'path': 'browse/journals',
            'content': 'Browse papers by journal',
            'count': len(journals),
            'feed_kind': 'navigation',
        },
        {
            'id': 'urn:papervisor:opds:browse:paper-tags',
            'title': 'Tags',
            'path': 'browse/paper-tags',
            'content': 'Browse papers by tags',
            'count': len(paper_tags),
            'feed_kind': 'navigation',
        },
        {
            'id': 'urn:papervisor:opds:browse:years',
            'title': 'Publication Years',
            'path': 'browse/years',
            'content': 'Browse papers by publication year',
            'count': len(publication_years),
            'feed_kind': 'navigation',
        },
    ]
    entries = _nav_entries_from_specs(ctx=ctx, specs=specs)
    return _static_menu_navigation_feed_response(
        ctx=ctx,
        entries=entries,
        feed_id='urn:papervisor:opds:browse:papers',
        title='Browse Papers',
        subtitle='Paper facets: authors, journals, tags, year',
        path='browse/papers',
        up_href=ctx.url.build('browse'),
    )


@app.get('/opds/browse/books')
def browse_books_menu(ctx: OPDSContext = Depends(opds_context)):
    """Book facet navigation."""
    book_authors = opds.get_authors(ctx.user.id, file_type='book')
    series = opds.get_series(ctx.user.id)
    genres = opds.get_genres(ctx.user.id)
    book_publishers = opds.get_publishers(ctx.user.id, file_type='book')
    book_languages = opds.get_languages(ctx.user.id, file_type='book')

    specs: list[dict[str, object]] = [
        {
            'id': 'urn:papervisor:opds:browse:book-authors',
            'title': 'Authors',
            'path': 'browse/book-authors',
            'content': 'Browse books by author',
            'count': len(book_authors),
            'feed_kind': 'navigation',
        },
        {
            'id': 'urn:papervisor:opds:browse:series',
            'title': 'Series',
            'path': 'browse/series',
            'content': 'Browse books by series',
            'count': len(series),
            'feed_kind': 'navigation',
        },
        {
            'id': 'urn:papervisor:opds:browse:genres',
            'title': 'Genres',
            'path': 'browse/genres',
            'content': 'Browse books by genre',
            'count': len(genres),
            'feed_kind': 'navigation',
        },
        {
            'id': 'urn:papervisor:opds:browse:book-publishers',
            'title': 'Publishers',
            'path': 'browse/book-publishers',
            'content': 'Browse books by publisher',
            'count': len(book_publishers),
            'feed_kind': 'navigation',
        },
        {
            'id': 'urn:papervisor:opds:browse:book-languages',
            'title': 'Languages',
            'path': 'browse/book-languages',
            'content': 'Browse books by language',
            'count': len(book_languages),
            'feed_kind': 'navigation',
        },
    ]
    entries = _nav_entries_from_specs(ctx=ctx, specs=specs)
    return _static_menu_navigation_feed_response(
        ctx=ctx,
        entries=entries,
        feed_id='urn:papervisor:opds:browse:books',
        title='Browse Books',
        subtitle='Book facets: authors, series, genres, publisher, language',
        path='browse/books',
        up_href=ctx.url.build('browse'),
    )


@app.get('/opds/browse/book-authors')
def book_authors_list(ctx: OPDSContext = Depends(opds_context)):
    """List all book authors."""
    authors = opds.get_authors(ctx.user.id, file_type='book')

    return _browse_named_count_list_response(
        ctx=ctx,
        items=authors,
        id_prefix='urn:papervisor:opds:browse:book-author:',
        href_prefix='browse/book-authors/',
        content_template='{count} books',
        feed_id='urn:papervisor:opds:browse:book-authors',
        title='Book Authors',
        path='browse/book-authors',
        subtitle_suffix='authors',
        encode_id=True,
        encode_href=True,
    )


@app.get('/opds/browse/book-authors/{author}')
def book_author_papers(author: str, page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Books by a specific author."""
    return _browse_author_acquisition_response(
        ctx=ctx,
        author=author,
        page=page,
        per_page=per_page,
        file_type='book',
        feed_id_prefix='urn:papervisor:opds:browse:book-author:',
        title_prefix='Books by',
        path_prefix='browse/book-authors/',
        up_path='browse/book-authors',
    )


@app.get('/opds/browse/paper-authors')
def paper_authors_list(ctx: OPDSContext = Depends(opds_context)):
    """List all paper authors."""
    authors = opds.get_authors(ctx.user.id, file_type='paper')

    return _browse_named_count_list_response(
        ctx=ctx,
        items=authors,
        id_prefix='urn:papervisor:opds:browse:paper-author:',
        href_prefix='browse/paper-authors/',
        content_template='{count} papers',
        feed_id='urn:papervisor:opds:browse:paper-authors',
        title='Paper Authors',
        path='browse/paper-authors',
        subtitle_suffix='authors',
        encode_id=True,
        encode_href=True,
    )


@app.get('/opds/browse/paper-authors/{author}')
def paper_author_papers(author: str, page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Papers by a specific author."""
    return _browse_author_acquisition_response(
        ctx=ctx,
        author=author,
        page=page,
        per_page=per_page,
        file_type='paper',
        feed_id_prefix='urn:papervisor:opds:browse:paper-author:',
        title_prefix='Papers by',
        path_prefix='browse/paper-authors/',
        up_path='browse/paper-authors',
    )


@app.get('/opds/browse/series')
def series_list(ctx: OPDSContext = Depends(opds_context)):
    """List all series."""
    series = opds.get_series(ctx.user.id)

    return _browse_named_count_list_response(
        ctx=ctx,
        items=series,
        id_prefix='urn:papervisor:opds:browse:series:',
        href_prefix='browse/series/',
        content_template='{count} books',
        feed_id='urn:papervisor:opds:browse:series',
        title='Series',
        path='browse/series',
        subtitle_suffix='series',
        encode_id=True,
        encode_href=True,
    )


@app.get('/opds/browse/series/{series}')
def series_books(series: str, page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Books in a specific series."""
    return _browse_named_acquisition_response(
        ctx=ctx,
        name=series,
        page=page,
        per_page=per_page,
        fetcher=opds.get_papers_by_series,
        feed_id_prefix='urn:papervisor:opds:browse:series:',
        title_prefix='Series:',
        path_prefix='browse/series/',
        up_path='browse/series',
    )


@app.get('/opds/browse/genres')
def genres_list(ctx: OPDSContext = Depends(opds_context)):
    """List all genres."""
    genres = opds.get_genres(ctx.user.id)

    return _browse_named_count_list_response(
        ctx=ctx,
        items=genres,
        id_prefix='urn:papervisor:opds:browse:genre:',
        href_prefix='browse/genres/',
        content_template='{count} books',
        feed_id='urn:papervisor:opds:browse:genres',
        title='Genres',
        path='browse/genres',
        subtitle_suffix='genres',
        encode_id=True,
        encode_href=True,
    )


@app.get('/opds/browse/genres/{genre}')
def genre_books(genre: str, page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Books in a specific genre."""
    return _browse_named_acquisition_response(
        ctx=ctx,
        name=genre,
        page=page,
        per_page=per_page,
        fetcher=opds.get_papers_by_genre,
        feed_id_prefix='urn:papervisor:opds:browse:genre:',
        title_prefix='Genre:',
        path_prefix='browse/genres/',
        up_path='browse/genres',
    )


@app.get('/opds/browse/journals')
def journals_list(ctx: OPDSContext = Depends(opds_context)):
    """List all journals."""
    journals = opds.get_journals(ctx.user.id)

    return _browse_named_count_list_response(
        ctx=ctx,
        items=journals,
        id_prefix='urn:papervisor:opds:browse:journal:',
        href_prefix='browse/journals/',
        content_template='{count} papers',
        feed_id='urn:papervisor:opds:browse:journals',
        title='Journals',
        path='browse/journals',
        subtitle_suffix='journals',
        encode_id=True,
        encode_href=True,
    )


@app.get('/opds/browse/journals/{journal}')
def journal_papers(journal: str, page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Papers from a specific journal."""
    return _browse_named_acquisition_response(
        ctx=ctx,
        name=journal,
        page=page,
        per_page=per_page,
        fetcher=opds.get_papers_by_journal,
        feed_id_prefix='urn:papervisor:opds:browse:journal:',
        title_prefix='Journal:',
        path_prefix='browse/journals/',
        up_path='browse/journals',
    )


@app.get('/opds/browse/languages')
def languages_list(ctx: OPDSContext = Depends(opds_context)):
    """List all languages (books and papers)."""
    languages = opds.get_languages(ctx.user.id)

    return _browse_named_count_list_response(
        ctx=ctx,
        items=languages,
        id_prefix='urn:papervisor:opds:browse:language:',
        href_prefix='browse/languages/',
        content_template='{count} items',
        feed_id='urn:papervisor:opds:browse:languages',
        title='Languages',
        path='browse/languages',
        subtitle_suffix='languages',
        encode_id=True,
        encode_href=True,
    )


@app.get('/opds/browse/languages/{language}')
def language_papers(language: str, page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Items in a specific language."""
    return _browse_named_acquisition_response(
        ctx=ctx,
        name=language,
        page=page,
        per_page=per_page,
        fetcher=opds.get_papers_by_language,
        feed_id_prefix='urn:papervisor:opds:browse:language:',
        title_prefix='Language:',
        path_prefix='browse/languages/',
        up_path='browse/languages',
    )


@app.get('/opds/browse/book-languages')
def book_languages_list(ctx: OPDSContext = Depends(opds_context)):
    """List languages for books only."""
    languages = opds.get_languages(ctx.user.id, file_type='book')

    return _browse_named_count_list_response(
        ctx=ctx,
        items=languages,
        id_prefix='urn:papervisor:opds:browse:book-language:',
        href_prefix='browse/book-languages/',
        content_template='{count} books',
        feed_id='urn:papervisor:opds:browse:book-languages',
        title='Book Languages',
        path='browse/book-languages',
        subtitle_suffix='languages',
        encode_id=True,
        encode_href=True,
    )


@app.get('/opds/browse/book-languages/{language}')
def book_language_papers(language: str, page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Books in a specific language."""
    return _browse_named_acquisition_response(
        ctx=ctx,
        name=language,
        page=page,
        per_page=per_page,
        fetcher=lambda user_id, value, limit=50, offset=0: opds.get_papers_by_language(
            user_id,
            value,
            limit=limit,
            offset=offset,
            file_type='book',
        ),
        feed_id_prefix='urn:papervisor:opds:browse:book-language:',
        title_prefix='Book Language:',
        path_prefix='browse/book-languages/',
        up_path='browse/book-languages',
    )


@app.get('/opds/browse/book-publishers')
def book_publishers_list(ctx: OPDSContext = Depends(opds_context)):
    """List publishers for books only."""
    publishers = opds.get_publishers(ctx.user.id, file_type='book')

    return _browse_named_count_list_response(
        ctx=ctx,
        items=publishers,
        id_prefix='urn:papervisor:opds:browse:book-publisher:',
        href_prefix='browse/book-publishers/',
        content_template='{count} books',
        feed_id='urn:papervisor:opds:browse:book-publishers',
        title='Book Publishers',
        path='browse/book-publishers',
        subtitle_suffix='publishers',
        encode_id=True,
        encode_href=True,
    )


@app.get('/opds/browse/book-publishers/{publisher}')
def book_publisher_papers(publisher: str, page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Books from a specific publisher."""
    return _browse_named_acquisition_response(
        ctx=ctx,
        name=publisher,
        page=page,
        per_page=per_page,
        fetcher=lambda user_id, value, limit=50, offset=0: opds.get_papers_by_publisher(
            user_id,
            value,
            limit=limit,
            offset=offset,
            file_type='book',
        ),
        feed_id_prefix='urn:papervisor:opds:browse:book-publisher:',
        title_prefix='Publisher:',
        path_prefix='browse/book-publishers/',
        up_path='browse/book-publishers',
    )


@app.get('/opds/browse/tags')
def tags_list(ctx: OPDSContext = Depends(opds_context)):
    """List tags across books and papers."""
    tags = opds.get_tags(ctx.user.id)

    return _browse_named_count_list_response(
        ctx=ctx,
        items=tags,
        id_prefix='urn:papervisor:opds:browse:tag:',
        href_prefix='browse/tags/',
        content_template='{count} items',
        feed_id='urn:papervisor:opds:browse:tags',
        title='Tags',
        path='browse/tags',
        subtitle_suffix='tags',
        encode_id=True,
        encode_href=True,
    )


@app.get('/opds/browse/tags/{tag}')
def tag_papers(tag: str, page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Items by tag."""
    return _browse_named_acquisition_response(
        ctx=ctx,
        name=tag,
        page=page,
        per_page=per_page,
        fetcher=opds.get_papers_by_tag,
        feed_id_prefix='urn:papervisor:opds:browse:tag:',
        title_prefix='Tag:',
        path_prefix='browse/tags/',
        up_path='browse/tags',
    )


@app.get('/opds/browse/paper-tags')
def paper_tags_list(ctx: OPDSContext = Depends(opds_context)):
    """List tags for papers only."""
    tags = opds.get_tags(ctx.user.id, file_type='paper')

    return _browse_named_count_list_response(
        ctx=ctx,
        items=tags,
        id_prefix='urn:papervisor:opds:browse:paper-tag:',
        href_prefix='browse/paper-tags/',
        content_template='{count} papers',
        feed_id='urn:papervisor:opds:browse:paper-tags',
        title='Paper Tags',
        path='browse/paper-tags',
        subtitle_suffix='tags',
        encode_id=True,
        encode_href=True,
    )


@app.get('/opds/browse/paper-tags/{tag}')
def paper_tag_papers(tag: str, page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Papers by tag."""
    return _browse_named_acquisition_response(
        ctx=ctx,
        name=tag,
        page=page,
        per_page=per_page,
        fetcher=lambda user_id, value, limit=50, offset=0: opds.get_papers_by_tag(
            user_id,
            value,
            limit=limit,
            offset=offset,
            file_type='paper',
        ),
        feed_id_prefix='urn:papervisor:opds:browse:paper-tag:',
        title_prefix='Paper Tag:',
        path_prefix='browse/paper-tags/',
        up_path='browse/paper-tags',
    )


@app.get('/opds/browse/years')
def years_list(ctx: OPDSContext = Depends(opds_context)):
    """List all publication years."""
    years = opds.get_publication_years(ctx.user.id)

    return _browse_named_count_list_response(
        ctx=ctx,
        items=years,
        id_prefix='urn:papervisor:opds:browse:year:',
        href_prefix='browse/years/',
        content_template='{count} papers',
        feed_id='urn:papervisor:opds:browse:years',
        title='Publication Years',
        path='browse/years',
        subtitle_suffix='years',
        encode_id=False,
        encode_href=False,
    )


@app.get('/opds/browse/years/{year}')
def year_papers(year: str, page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Papers published in a specific year."""
    return _browse_named_acquisition_response(
        ctx=ctx,
        name=year,
        page=page,
        per_page=per_page,
        fetcher=opds.get_papers_by_year,
        feed_id_prefix='urn:papervisor:opds:browse:year:',
        title_prefix='Published in',
        path_prefix='browse/years/',
        up_path='browse/years',
        encode_path_component=False,
    )


# ============================================================================
# Search
# ============================================================================

@app.get('/opds/search')
def search_descriptor(request: Request):
    """OpenSearch descriptor."""
    _check_enabled()
    base_url = _get_base_url(request)
    api_key = _get_api_key(request)
    key_param = _get_api_key_param(api_key)

    xml = opds.generate_opensearch_descriptor(base_url, key_param)
    
    return Response(content=xml, media_type='application/opensearchdescription+xml;charset=utf-8')


@app.get('/opds/search/')
def search_results(q: str = '', page: int = 1, per_page: int = 50, ctx: OPDSContext = Depends(opds_context)):
    """Search results."""
    if not q:
        raise HTTPException(status_code=400, detail='Query parameter q is required')

    return _paginated_acquisition(
        ctx=ctx,
        page=page,
        per_page=per_page,
        fetcher=opds.search_papers,
        feed_id='urn:papervisor:opds:search',
        title=f'Search Results: {q}',
        subtitle_builder=lambda papers: f'Found {len(papers)} results',
        path='search/',
        query_params={'q': q},
        query=q,
    )


# ============================================================================
# File Download
# ============================================================================

@app.get('/opds/get/{paper_id}')
def download_paper(request: Request, paper_id: str, ctx: OPDSContext = Depends(opds_context)):
    """Download paper file with streaming support for Boox devices."""
    paper = opds.get_paper_by_id(ctx.user.id, paper_id)
    
    if not paper or not paper.file_path:
        raise HTTPException(status_code=404, detail='Paper not found or no file available')
    
    file_path = _resolve_library_file_path(paper.file_path)
    if file_path is None:
        raise HTTPException(status_code=404, detail='File not found on disk')
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail='File not found on disk')
    
    # Update access statistics (best effort).
    try:
        record_opened(paper_id=str(paper_id))
    except (SQLAlchemyError, RuntimeError, ValueError):
        logging.getLogger(__name__).debug('record_opened failed for %s', paper_id, exc_info=True)
    
    # Use StreamingResponse with chunked transfer for better compatibility with Boox devices
    # Boox devices can have issues with FileResponse on larger files
    def iterfile():
        with open(file_path, mode="rb") as file_like:
            while chunk := file_like.read(65536):  # 64KB chunks
                yield chunk
    
    # Get file size for Content-Length header
    file_size = file_path.stat().st_size
    
    return StreamingResponse(
        iterfile(),
        media_type='application/octet-stream',
        headers={
            'Content-Disposition': f'attachment; filename="{file_path.name}"',
            'Content-Length': str(file_size),
            'Accept-Ranges': 'bytes',
        }
    )
